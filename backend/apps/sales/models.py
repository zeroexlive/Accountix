"""Sales models (Sprint 05).

Conventions deliberately mirror purchasing (ADR-016) so the two cycles
read the same way:

- Warehouse is carried **per invoice** (and inherited by its return).
- Document numbers are unique **per company**.
- Discount is **line-level absolute only**; tax is a per-line **rate
  snapshot** plus the computed amount snapshot written at posting.
- Posting status and payment status are separate dimensions (§8):
  ``status`` is DRAFT/POSTED/REVERSED, ``payment_status`` starts UNPAID
  and is only moved by treasury (Sprint 06) — nothing in this sprint
  records payments.
- Invoice totals are snapshots written by the posting service and always
  equal the sum of their lines (tested).
- Posted documents and their lines are immutable; the only permitted
  mutation is the POSTED -> REVERSED flip performed by the reversal
  service.

Sales-specific choices are ADR-020 (two journal entries per invoice:
revenue + COGS) and ADR-021 (sales returns restore stock at the original
sale's COGS unit cost).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Product, Unit
from apps.core.models import TimeStampedUUIDModel
from apps.inventory.models import Warehouse
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.sales import services

_IMMUTABLE_STATUSES = ("POSTED", "REVERSED")


def _guard_immutable(instance, model, mutable_fields, label):
    """Posted-document guard (same pattern as purchases): once POSTED or
    REVERSED a document may only flip POSTED -> REVERSED with every other
    tracked field identical. Sole sanctioned exception (ADR-024,
    Sprint 06): on a model that carries ``payment_status``, that field —
    and only that field — may change while POSTED, because treasury's
    allocation service owns it and recomputes it from allocations."""
    if instance.pk:
        old = model.objects.filter(pk=instance.pk).first()
        if old is not None and old.status in _IMMUTABLE_STATUSES:
            flip = (
                old.status == "POSTED"
                and instance.status == "REVERSED"
                and all(
                    getattr(old, f) == getattr(instance, f) for f in mutable_fields - {"status"}
                )
            )
            payment_status_only = (
                "payment_status" in mutable_fields
                and old.status == "POSTED"
                and instance.status == old.status
                and all(
                    getattr(old, f) == getattr(instance, f)
                    for f in mutable_fields - {"status", "payment_status"}
                )
            )
            if not (flip or payment_status_only):
                raise ValidationError(f"Posted {label} are immutable; reverse instead.")


class _LineGuardMixin:
    """Lines of a posted document are immutable (mirrors purchases).

    Subclasses set ``_parent_attr`` (the FK attribute name) and
    ``_parent_model``; quotations are guarded only once CONVERTED.
    """

    _parent_attr = ""
    _parent_model = None
    _label = "document"
    _guard_statuses = _IMMUTABLE_STATUSES

    def _guard_mutable(self):
        parent_id = getattr(self, f"{self._parent_attr}_id", None)
        if parent_id and self._parent_model is not None:
            status = (
                self._parent_model.objects.filter(pk=parent_id)
                .values_list("status", flat=True)
                .first()
            )
            if status in self._guard_statuses:
                raise ValidationError(f"Lines of a posted {self._label} are immutable.")

    def save(self, *args, **kwargs):
        self._guard_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_mutable()
        return super().delete(*args, **kwargs)


# ---------------------------------------------------------------------------
# Quotation
# ---------------------------------------------------------------------------


class SalesQuotation(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SENT = "SENT", "Sent"
        CONVERTED = "CONVERTED", "Converted"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sales_quotations")
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="sales_quotations")
    quotation_number = models.CharField(max_length=32)
    quotation_date = models.DateField()
    valid_until = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["quotation_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "quotation_number"], name="uniq_quotation_number_per_company"
            )
        ]

    def __str__(self):
        return f"Quote {self.quotation_number} [{self.status}]"


class SalesQuotationLine(_LineGuardMixin, TimeStampedUUIDModel):
    _parent_attr = "quotation"
    _label = "sales quotation"
    _guard_statuses = ("CONVERTED",)

    quotation = models.ForeignKey(SalesQuotation, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sales_quotation_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_quotation_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    unit_price = models.DecimalField(max_digits=19, decimal_places=2)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="sales_quote_line_qty_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="sales_quote_line_price_non_neg"
            ),
        ]

    def clean(self):
        super().clean()
        services.validate_quotation_line(self)

    def __str__(self):
        return f"{self.product.sku} x {self.quantity}"


SalesQuotationLine._parent_model = SalesQuotation


# ---------------------------------------------------------------------------
# Invoice
# ---------------------------------------------------------------------------

_INVOICE_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "customer_id",
    "quotation_id",
    "invoice_number",
    "invoice_date",
    "warehouse_id",
    "status",
    "payment_status",
    "description",
    "subtotal",
    "discount_total",
    "tax_total",
    "grand_total",
    "stock_document_id",
    "journal_entry_id",
    "cogs_journal_entry_id",
    "posted_by_id",
    "posted_at",
}


class SalesInvoice(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sales_invoices")
    customer = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="sales_invoices")
    quotation = models.ForeignKey(
        SalesQuotation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    invoice_number = models.CharField(max_length=32)
    invoice_date = models.DateField()
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="sales_invoices"
    )
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    payment_status = models.CharField(
        max_length=15, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID
    )
    description = models.CharField(max_length=500, blank=True)
    # Totals snapshot — written by the posting service, sum of the lines.
    subtotal = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    discount_total = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    grand_total = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    stock_document = models.ForeignKey(
        "inventory.StockDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
    )
    # Revenue entry (ADR-020): Dr receivables / Cr revenue / Cr tax payable.
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices",
    )
    # COGS entry (ADR-020): Dr COGS / Cr inventory at the issue value.
    cogs_journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_invoices_cogs",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_sales_invoices",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["invoice_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "invoice_number"], name="uniq_sales_invoice_number"
            )
        ]

    def save(self, *args, **kwargs):
        _guard_immutable(self, SalesInvoice, _INVOICE_MUTABLE_FIELDS, "sales invoices")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_STATUSES:
            raise ValidationError("Posted sales invoices cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Sales {self.invoice_number} [{self.status}]"


class SalesInvoiceLine(_LineGuardMixin, TimeStampedUUIDModel):
    _parent_attr = "invoice"
    _label = "sales invoice"

    invoice = models.ForeignKey(SalesInvoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sales_invoice_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_invoice_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    unit_price = models.DecimalField(max_digits=19, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=19, decimal_places=4, default=0)  # e.g. 0.1000
    tax_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)  # snapshot

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="sales_line_qty_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="sales_line_price_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0), name="sales_line_discount_non_neg"
            ),
            models.CheckConstraint(
                condition=models.Q(tax_rate__gte=0), name="sales_line_tax_rate_non_negative"
            ),
        ]

    def clean(self):
        super().clean()
        services.validate_invoice_line(self)

    def gross_amount(self):
        from decimal import ROUND_HALF_UP, Decimal

        return (self.quantity * self.unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def net_amount(self):
        """Gross minus this line's discount — the taxable revenue base."""
        return self.gross_amount() - self.discount_amount

    def __str__(self):
        return f"{self.product.sku} x {self.quantity} @ {self.unit_price}"


SalesInvoiceLine._parent_model = SalesInvoice


# ---------------------------------------------------------------------------
# Return
# ---------------------------------------------------------------------------

_RETURN_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "original_invoice_id",
    "return_number",
    "return_date",
    "status",
    "description",
    "net_total",
    "tax_total",
    "total_amount",
    "cogs_value",
    "stock_document_id",
    "journal_entry_id",
    "cogs_journal_entry_id",
    "posted_by_id",
    "posted_at",
}


class SalesReturn(TimeStampedUUIDModel):
    """Goods returned by the customer of a POSTED sales invoice.

    Stock is restored at the original sale's COGS unit cost (ADR-021), so
    the credit back into COGS exactly offsets the cost that left at sale
    time. Revenue/tax reversals are proportional shares of the original
    invoice lines (see ``services.post_sales_return``).
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"  # via reverse_*_return services (Sprint 07)

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sales_returns")
    original_invoice = models.ForeignKey(
        SalesInvoice, on_delete=models.PROTECT, related_name="returns"
    )
    return_number = models.CharField(max_length=32)
    return_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    description = models.CharField(max_length=500, blank=True)
    net_total = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    tax_total = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    cogs_value = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    stock_document = models.ForeignKey(
        "inventory.StockDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_returns",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_returns",
    )
    cogs_journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_returns_cogs",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_sales_returns",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["return_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "return_number"], name="uniq_sales_return_number"
            )
        ]

    @property
    def customer(self):
        return self.original_invoice.customer

    def save(self, *args, **kwargs):
        _guard_immutable(self, SalesReturn, _RETURN_MUTABLE_FIELDS, "sales returns")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_STATUSES:
            raise ValidationError("Posted sales returns cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Sales return {self.return_number} [{self.status}]"


class SalesReturnLine(_LineGuardMixin, TimeStampedUUIDModel):
    _parent_attr = "sales_return"
    _label = "sales return"

    sales_return = models.ForeignKey(SalesReturn, on_delete=models.CASCADE, related_name="lines")
    invoice_line = models.ForeignKey(
        SalesInvoiceLine, on_delete=models.PROTECT, related_name="return_lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="sales_return_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="sales_return_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="sales_return_line_qty_positive"
            )
        ]

    def clean(self):
        super().clean()
        services.validate_return_line(self)

    def __str__(self):
        return f"Return {self.product.sku} x {self.quantity}"


SalesReturnLine._parent_model = SalesReturn
