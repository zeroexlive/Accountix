"""Treasury models (Sprint 06).

Design choices (ADRs in DECISIONS.md):

- **One ``TreasuryAccount`` table** with ``kind`` CASH/BANK (ADR-022).
  The master prompt §13.2 names ``CashAccount`` and ``BankAccount`` as
  separate entities; they are the same concept here - a company-owned
  store of money mapped to exactly one GL account - and payments need a
  single FK target, so the two concepts are modelled as one table with a
  kind discriminator. Bank-only fields are nullable and required (by the
  service layer) only for ``kind=BANK``.
- A treasury account carries its **GL account link**: that link is the
  mapping that lets treasury post journals without hardcoded account
  codes (the ADR-011/013 discipline - accounts come from data or from
  the caller, never from constants).
- ``Payment`` is a posted-document like the invoices: DRAFT/POSTED/
  REVERSED, immutable once posted except the POSTED -> REVERSED flip.
- ``PaymentAllocation`` rows are written **only** by the treasury
  service. Voided allocations stay in the table with status VOID
  (ADR-025): allocation history is never silently deleted.
- ``Cheque`` implements the Iranian cheque register (section 10):
  received cheques are an asset in hand - not cash - until cleared;
  issued cheques sit in a caller-supplied holding (cheques payable)
  account until they clear against the bank.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.accounting.models import Account, JournalEntry
from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.purchases.models import PurchaseInvoice
from apps.sales.models import SalesInvoice


class TreasuryAccount(TimeStampedUUIDModel):
    class Kind(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK = "BANK", "Bank"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="treasury_accounts")
    kind = models.CharField(max_length=4, choices=Kind.choices)
    name = models.CharField(max_length=200)
    # Bank-only details; blank for cash accounts (validated in services).
    bank_name = models.CharField(max_length=200, blank=True)
    account_number = models.CharField(max_length=64, blank=True)
    gl_account = models.ForeignKey(
        Account, on_delete=models.PROTECT, related_name="treasury_accounts"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "name"], name="uniq_treasury_account_name_per_company"
            )
        ]

    def __str__(self):
        return f"{self.name} [{self.kind}]"


_PAYMENT_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "direction",
    "party_id",
    "treasury_account_id",
    "method",
    "amount",
    "payment_date",
    "reference",
    "description",
    "status",
    "counterparty_account_id",
    "journal_entry_id",
    "posted_by_id",
    "posted_at",
}


class Payment(TimeStampedUUIDModel):
    class Direction(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt"
        PAYMENT = "PAYMENT", "Payment"

    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank transfer"
        CHEQUE = "CHEQUE", "Cheque"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="payments")
    direction = models.CharField(max_length=7, choices=Direction.choices)
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="payments")
    treasury_account = models.ForeignKey(
        TreasuryAccount, on_delete=models.PROTECT, related_name="payments"
    )
    method = models.CharField(max_length=13, choices=Method.choices, default=Method.CASH)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    payment_date = models.DateField()
    reference = models.CharField(max_length=64, blank=True)
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.DRAFT)
    # The AR (receipt) or AP (payment) account used at posting time,
    # supplied by the caller; stored so reversals, cheque bounces and
    # clearing can act later without re-asking for the mapping.
    counterparty_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="treasury_payments",
    )
    journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treasury_payments",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_payments",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["payment_date", "created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive")
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            old = Payment.objects.filter(pk=self.pk).first()
            if old is not None and old.status in ("POSTED", "REVERSED"):
                allowed = (
                    old.status == "POSTED"
                    and self.status == "REVERSED"
                    and all(
                        getattr(old, f) == getattr(self, f)
                        for f in _PAYMENT_MUTABLE_FIELDS - {"status"}
                    )
                )
                if not allowed:
                    raise ValidationError("Posted payments are immutable; reverse instead.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk:
            old = Payment.objects.filter(pk=self.pk).first()
            if old is not None and old.status in ("POSTED", "REVERSED"):
                raise ValidationError("Posted payments cannot be deleted; reverse instead.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.direction} {self.amount} [{self.status}]"


class PaymentAllocation(TimeStampedUUIDModel):
    """An allocation of part (or all) of a POSTED payment to one invoice.

    Exactly one of ``sales_invoice`` / ``purchase_invoice`` is set.
    Rows are created and voided only by ``treasury.services`` (ADR-023,
    ADR-025); VOID rows are kept for audit history and never counted.
    """

    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        VOID = "VOID", "Void"

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="payment_allocations"
    )
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")
    sales_invoice = models.ForeignKey(
        SalesInvoice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_allocations",
    )
    purchase_invoice = models.ForeignKey(
        PurchaseInvoice,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payment_allocations",
    )
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.ACTIVE)
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount__gt=0), name="allocation_amount_positive"
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(sales_invoice__isnull=False, purchase_invoice__isnull=True)
                    | models.Q(sales_invoice__isnull=True, purchase_invoice__isnull=False)
                ),
                name="allocation_exactly_one_target",
            ),
        ]

    @property
    def invoice(self):
        return self.sales_invoice or self.purchase_invoice

    def __str__(self):
        return f"Allocation {self.amount} [{self.status}]"


class Cheque(TimeStampedUUIDModel):
    """Cheque register entry (section 10 Iranian workflow).

    ``holding_account`` is the GL account the cheque's value sits in
    while it is not yet bank money: for RECEIVED cheques the caller's
    cheques-in-hand account; for ISSUED cheques the caller's cheques
    payable account. It is fixed at payment posting time.
    """

    class Direction(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        ISSUED = "ISSUED", "Issued"

    class Status(models.TextChoices):
        RECEIVED = "RECEIVED", "Received"
        DEPOSITED = "DEPOSITED", "Deposited"
        DELIVERED = "DELIVERED", "Delivered"
        CLEARED = "CLEARED", "Cleared"
        BOUNCED = "BOUNCED", "Bounced"
        RETURNED = "RETURNED", "Returned"
        REVERSED = "REVERSED", "Reversed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cheques")
    direction = models.CharField(max_length=8, choices=Direction.choices)
    payment = models.ForeignKey(
        Payment, on_delete=models.PROTECT, null=True, blank=True, related_name="cheques"
    )
    bank_name = models.CharField(max_length=200, blank=True)
    cheque_number = models.CharField(max_length=64)
    # Sayad registration id - an optional plain field; no external
    # registry validation is performed or claimed (prompt section 12.4).
    sayad_id = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    issue_date = models.DateField(null=True, blank=True)
    due_date = models.DateField()
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.RECEIVED)
    holding_account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cheques",
    )
    clearing_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cheque_clearings",
    )
    bounce_journal_entry = models.ForeignKey(
        JournalEntry,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cheque_bounces",
    )

    class Meta:
        ordering = ["due_date", "created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="cheque_amount_positive"),
            models.UniqueConstraint(
                fields=["company", "direction", "bank_name", "cheque_number"],
                name="uniq_cheque_number_per_company_bank",
            ),
        ]

    def __str__(self):
        return f"Cheque {self.cheque_number} {self.amount} [{self.status}]"
