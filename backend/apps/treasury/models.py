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


class BankStatement(TimeStampedUUIDModel):
    """One bank statement for one BANK treasury account (Sprint 14,
    ADR-041). Reconciliation happens at the GL level: the book side of
    a statement is the set of posted journal lines on the treasury
    account's GL account, and a statement line reconciles by *linking*
    to exactly one of those lines — matching never mutates the
    journal, the payment or the cheque behind the line.

    ``opening_balance`` / ``closing_balance`` are the balances *as
    stated by the bank* for [start_date, end_date]; everything else in
    the reconciliation summary is derived.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        COMPLETED = "COMPLETED", "Completed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="bank_statements")
    treasury_account = models.ForeignKey(
        TreasuryAccount, on_delete=models.PROTECT, related_name="bank_statements"
    )
    start_date = models.DateField()
    end_date = models.DateField()
    opening_balance = models.DecimalField(max_digits=19, decimal_places=2)
    closing_balance = models.DecimalField(max_digits=19, decimal_places=2)
    source_note = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ["-end_date", "-created_at"]

    def __str__(self):
        return f"Statement {self.treasury_account.name} {self.start_date}..{self.end_date} [{self.status}]"


class BankStatementLine(TimeStampedUUIDModel):
    """One line of a bank statement. ``amount`` is SIGNED from the
    bank's perspective: positive (a bank credit) is money IN to the
    account, negative (a bank debit) is money OUT. It therefore equals
    ``debit - credit`` of the bank-GL journal line it matches (the
    bank account is debit-normal), which is the sign mapping the
    matcher enforces (ADR-041).

    ``matched_journal_line`` is a OneToOne: the database itself
    guarantees a journal line is matched at most once across all
    statements, so two statements can never claim the same book
    movement.
    """

    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="bank_statement_lines"
    )
    statement = models.ForeignKey(BankStatement, on_delete=models.CASCADE, related_name="lines")
    line_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    reference = models.CharField(max_length=64, blank=True)
    amount = models.DecimalField(max_digits=19, decimal_places=2)
    matched_journal_line = models.OneToOneField(
        "accounting.JournalLine",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="bank_statement_match",
    )
    matched_at = models.DateTimeField(null=True, blank=True)
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="matched_statement_lines",
    )

    class Meta:
        ordering = ["line_date", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(amount=0), name="statement_line_amount_non_zero"
            )
        ]

    @property
    def is_matched(self):
        return self.matched_journal_line_id is not None

    def __str__(self):
        return f"Statement line {self.line_date} {self.amount}"


class ChequeBook(TimeStampedUUIDModel):
    """A physical cheque book of ONE bank treasury account (Sprint 15,
    ADR-042): a sequential range of leaves used for ISSUED cheques
    only — received cheques are other parties' paper and never come
    from a book. The book itself is just the range record; the leaves
    carry the state. Books are never deleted; a book is "active"
    exactly while it still has UNUSED leaves (derived, not stored).
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cheque_books")
    treasury_account = models.ForeignKey(
        TreasuryAccount, on_delete=models.PROTECT, related_name="cheque_books"
    )
    label = models.CharField(max_length=200, blank=True)
    first_number = models.CharField(max_length=64)
    leaf_count = models.PositiveIntegerField()

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Cheque book {self.label or self.first_number} ({self.treasury_account.name})"


class ChequeLeaf(TimeStampedUUIDModel):
    """One leaf of a cheque book. ``number`` is the printed leaf
    identifier (in current Iranian practice the Sayad id string).

    Uniqueness is enforced at the ACCOUNT level: no two leaves of the
    same bank treasury account may share a number, across all of the
    account's books — so overlapping book ranges are impossible by
    construction (ADR-042).

    A leaf is consumed exactly once, when an issued cheque is created
    from it (``services.create_payment(..., leaf=...)``): status flips
    to USED and ``cheque`` links the cheque row. Nothing resurrects a
    used leaf — not payment reversal, not a bounce: the physical leaf
    has left the book.
    """

    class Status(models.TextChoices):
        UNUSED = "UNUSED", "Unused"
        USED = "USED", "Used"
        VOID = "VOID", "Void"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cheque_leaves")
    treasury_account = models.ForeignKey(
        TreasuryAccount, on_delete=models.PROTECT, related_name="cheque_leaves"
    )
    book = models.ForeignKey(ChequeBook, on_delete=models.CASCADE, related_name="leaves")
    number = models.CharField(max_length=64)
    # 0-based position inside the book: stable display order even when
    # the numeric counter outgrows its zero-padded width (999 -> 1000).
    position = models.PositiveIntegerField()
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.UNUSED)
    cheque = models.OneToOneField(
        Cheque,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="leaf",
    )

    class Meta:
        ordering = ["book", "position"]
        constraints = [
            models.UniqueConstraint(
                fields=["treasury_account", "number"],
                name="uniq_cheque_leaf_number_per_account",
            ),
            models.UniqueConstraint(
                fields=["book", "position"], name="uniq_cheque_leaf_position_per_book"
            ),
        ]

    def __str__(self):
        return f"Leaf {self.number} [{self.status}]"
