from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.accounting import services
from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company, FiscalPeriod


class Account(TimeStampedUUIDModel):
    """Chart-of-accounts node (Sprint 01). Journal models follow below."""

    class AccountType(models.TextChoices):
        ASSET = "ASSET", _("Asset")
        LIABILITY = "LIABILITY", _("Liability")
        EQUITY = "EQUITY", _("Equity")
        REVENUE = "REVENUE", _("Revenue")
        EXPENSE = "EXPENSE", _("Expense")

    class NormalBalance(models.TextChoices):
        DEBIT = "DEBIT", _("Debit")
        CREDIT = "CREDIT", _("Credit")

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="accounts")
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    account_type = models.CharField(max_length=10, choices=AccountType.choices)
    normal_balance = models.CharField(max_length=6, choices=NormalBalance.choices)
    is_postable = models.BooleanField(
        default=False
    )  # only leaf/postable accounts may receive postings later
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_account_code_per_company"
            )
        ]

    def clean(self):
        super().clean()
        services.validate_account_hierarchy(self)

    def __str__(self):
        return f"{self.code} — {self.name}"


_IMMUTABLE_STATUSES = ("POSTED", "REVERSED")
_ENTRY_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "fiscal_period_id",
    "entry_date",
    "description",
    "status",
    "source_type",
    "source_id",
    "idempotency_key",
    "reversal_of_id",
    "posted_by_id",
    "posted_at",
}


class JournalEntry(TimeStampedUUIDModel):
    """Double-entry journal header (Sprint 02).

    Reversal is modelled both as ``reversal_of`` on the reversal entry and
    as a dedicated ``JournalReversal`` record (ADR-009).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        VALIDATED = "VALIDATED", _("Validated")
        POSTED = "POSTED", _("Posted")
        REVERSED = "REVERSED", _("Reversed")

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="journal_entries")
    fiscal_period = models.ForeignKey(
        FiscalPeriod, on_delete=models.PROTECT, related_name="journal_entries"
    )
    entry_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    source_type = models.CharField(max_length=50, blank=True)  # e.g. MANUAL, SALES_INVOICE
    source_id = models.CharField(max_length=64, blank=True)
    idempotency_key = models.CharField(max_length=100, null=True, blank=True)
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_entries",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_journal_entries",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["entry_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "idempotency_key"],
                condition=models.Q(idempotency_key__isnull=False),
                name="uniq_entry_idempotency_per_company",
            )
        ]

    @property
    def is_reversal(self) -> bool:
        return self.reversal_of_id is not None

    def total_debit(self):
        from decimal import Decimal

        return sum((line.debit for line in self.lines.all()), Decimal("0"))

    def total_credit(self):
        from decimal import Decimal

        return sum((line.credit for line in self.lines.all()), Decimal("0"))

    def save(self, *args, **kwargs):
        if self.pk:
            old = JournalEntry.objects.filter(pk=self.pk).first()
            if old is not None and old.status in _IMMUTABLE_STATUSES:
                # Only allowed mutation: POSTED -> REVERSED with every other
                # field identical (the reversal service performs exactly this).
                allowed = (
                    old.status == "POSTED"
                    and self.status == "REVERSED"
                    and all(
                        getattr(old, f) == getattr(self, f)
                        for f in _ENTRY_MUTABLE_FIELDS - {"status"}
                    )
                )
                if not allowed:
                    raise ValidationError(
                        _("Posted journal entries are immutable; reverse the entry instead.")
                    )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_STATUSES:
            raise ValidationError(_("Posted journal entries cannot be deleted."))
        return super().delete(*args, **kwargs)

    def __str__(self):
        # Rendered on the payment detail page: the status must be
        # the translated display label, never the raw code (ADR-055).
        return f"{self.entry_date} {self.description} [{self.get_status_display()}]"


class JournalLine(TimeStampedUUIDModel):
    entry = models.ForeignKey(JournalEntry, on_delete=models.CASCADE, related_name="lines")
    account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name="journal_lines")
    # Optional subledger dimension (Sprint 04, ADR-015): a line may be
    # tagged with the counterparty it belongs to (e.g. the supplier on an
    # accounts-payable line) so party balances derive from journal lines.
    party = models.ForeignKey(
        "parties.Party",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_lines",
    )
    debit = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    credit = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(debit__gte=0) & models.Q(credit__gte=0),
                name="journal_line_amounts_non_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(debit=0) | models.Q(credit=0),
                name="journal_line_one_side_only",
            ),
            models.CheckConstraint(
                condition=models.Q(debit__gt=0) | models.Q(credit__gt=0),
                name="journal_line_non_zero",
            ),
        ]

    def _guard_mutable(self):
        if self.entry_id and self.entry.status in _IMMUTABLE_STATUSES:
            raise ValidationError(_("Lines of a posted journal entry are immutable."))

    def save(self, *args, **kwargs):
        # Refetch status to avoid acting on a stale in-memory entry.
        if self.entry_id:
            status = (
                JournalEntry.objects.filter(pk=self.entry_id)
                .values_list("status", flat=True)
                .first()
            )
            if status in _IMMUTABLE_STATUSES:
                raise ValidationError(_("Lines of a posted journal entry are immutable."))
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.account.code}: D{self.debit} / C{self.credit}"


class JournalReversal(TimeStampedUUIDModel):
    """Dedicated reversal record: who reversed what, with which entry, why."""

    original_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="reversal_record"
    )
    reversal_entry = models.OneToOneField(
        JournalEntry, on_delete=models.PROTECT, related_name="reverses_record"
    )
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="journal_reversals",
    )
    reason = models.CharField(max_length=500, blank=True)
    reversed_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"Reversal of {self.original_entry_id} by {self.reversal_entry_id}"
