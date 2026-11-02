"""Purchasing models (Sprint 04).

Design choices made here (documented as ADRs in DECISIONS.md):

- The warehouse is carried **per invoice** (and inherited by its return),
  not per line — a purchase invoice is received into one warehouse.
- Invoice numbers are unique **per company** (ADR-016), stricter than
  per-supplier, which keeps numbering auditable without a numbering
  service yet.
- Discount lives at **line level only**, as an absolute amount; the
  invoice discount total is the sum of line discounts. Tax is a per-line
  **rate snapshot** plus the computed amount snapshot written at posting;
  rates are data, never a hardcoded constant (prompt §12.4).
- Posting status and payment status are separate dimensions (§8):
  ``status`` is DRAFT/POSTED/REVERSED, ``payment_status`` starts UNPAID
  and is only moved by treasury (Sprint 06) — nothing in this sprint
  records payments.
- Invoice totals are snapshots written by the posting service at posting
  time and always equal the sum of their lines (tested).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Product, Unit
from apps.core.models import TimeStampedUUIDModel
from apps.inventory.models import Warehouse
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.purchases import services


class PurchaseOrder(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        APPROVED = "APPROVED", "Approved"
        CLOSED = "CLOSED", "Closed"
        CANCELLED = "CANCELLED", "Cancelled"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="purchase_orders")
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="purchase_orders")
    order_number = models.CharField(max_length=32)
    order_date = models.DateField()
    expected_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    description = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["order_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "order_number"], name="uniq_po_number_per_company"
            )
        ]

    def __str__(self):
        return f"PO {self.order_number} [{self.status}]"


class PurchaseOrderLine(TimeStampedUUIDModel):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_order_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_order_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    unit_price = models.DecimalField(max_digits=19, decimal_places=2)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="po_line_qty_positive"),
            models.CheckConstraint(
                condition=models.Q(unit_price__gte=0), name="po_line_price_non_negative"
            ),
        ]

    def clean(self):
        super().clean()
        services.validate_order_line(self)

    def __str__(self):
        return f"{self.product.sku} x {self.quantity}"


_INVOICE_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "supplier_id",
    "purchase_order_id",
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
    "posted_by_id",
    "posted_at",
}
_IMMUTABLE_STATUSES = ("POSTED", "REVERSED")


def _guard_immutable(instance, model, mutable_fields, label):
    """Shared posted-document guard: once POSTED/REVERSED a document may
    only flip POSTED -> REVERSED with every other field identical."""
    if instance.pk:
        old = model.objects.filter(pk=instance.pk).first()
        if old is not None and old.status in _IMMUTABLE_STATUSES:
            allowed = (
                old.status == "POSTED"
                and instance.status == "REVERSED"
                and all(
                    getattr(old, f) == getattr(instance, f) for f in mutable_fields - {"status"}
                )
            )
            if not allowed:
                raise ValidationError(f"Posted {label} are immutable; reverse instead.")


class PurchaseInvoice(TimeStampedUUIDModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    class PaymentStatus(models.TextChoices):
        UNPAID = "UNPAID", "Unpaid"
        PARTIALLY_PAID = "PARTIALLY_PAID", "Partially paid"
        PAID = "PAID", "Paid"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="purchase_invoices")
    supplier = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="purchase_invoices")
    purchase_order = models.ForeignKey(
        PurchaseOrder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
    )
    invoice_number = models.CharField(max_length=32)
    invoice_date = models.DateField()
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="purchase_invoices"
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
        related_name="purchase_invoices",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_invoices",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_purchase_invoices",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["invoice_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "invoice_number"], name="uniq_purchase_invoice_number"
            )
        ]

    def save(self, *args, **kwargs):
        _guard_immutable(self, PurchaseInvoice, _INVOICE_MUTABLE_FIELDS, "purchase invoices")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_STATUSES:
            raise ValidationError("Posted purchase invoices cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Purchase {self.invoice_number} [{self.status}]"


class PurchaseInvoiceLine(TimeStampedUUIDModel):
    invoice = models.ForeignKey(PurchaseInvoice, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_invoice_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_invoice_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=19, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=19, decimal_places=4, default=0)  # e.g. 0.1000
    tax_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)  # snapshot

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="purchase_line_qty_positive"
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0), name="purchase_line_cost_non_negative"
            ),
            models.CheckConstraint(
                condition=models.Q(discount_amount__gte=0), name="purchase_line_discount_non_neg"
            ),
            models.CheckConstraint(
                condition=models.Q(tax_rate__gte=0), name="purchase_line_tax_rate_non_negative"
            ),
        ]

    def clean(self):
        super().clean()
        services.validate_invoice_line(self)

    def gross_amount(self):
        from decimal import ROUND_HALF_UP, Decimal

        return (self.quantity * self.unit_cost).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def net_amount(self):
        """Gross minus this line's discount — the taxable, stock-valuation base."""
        return self.gross_amount() - self.discount_amount

    def _guard_mutable(self):
        if self.invoice_id:
            status = (
                PurchaseInvoice.objects.filter(pk=self.invoice_id)
                .values_list("status", flat=True)
                .first()
            )
            if status in _IMMUTABLE_STATUSES:
                raise ValidationError("Lines of a posted purchase invoice are immutable.")

    def save(self, *args, **kwargs):
        self._guard_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.product.sku} x {self.quantity} @ {self.unit_cost}"


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
    "total_amount",
    "stock_document_id",
    "journal_entry_id",
    "posted_by_id",
    "posted_at",
}


class PurchaseReturn(TimeStampedUUIDModel):
    """Goods returned to the supplier of a POSTED purchase invoice.

    The return is valued at the current moving average (that is what
    leaves the inventory ledger); the AP reduction equals that same
    value — see ``services.post_purchase_return`` and ADR-018.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"  # reserved; no reversal service yet

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="purchase_returns")
    original_invoice = models.ForeignKey(
        PurchaseInvoice, on_delete=models.PROTECT, related_name="returns"
    )
    return_number = models.CharField(max_length=32)
    return_date = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    description = models.CharField(max_length=500, blank=True)
    total_amount = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    stock_document = models.ForeignKey(
        "inventory.StockDocument",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_returns",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="purchase_returns",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_purchase_returns",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["return_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "return_number"], name="uniq_purchase_return_number"
            )
        ]

    @property
    def supplier(self):
        return self.original_invoice.supplier

    def save(self, *args, **kwargs):
        _guard_immutable(self, PurchaseReturn, _RETURN_MUTABLE_FIELDS, "purchase returns")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_STATUSES:
            raise ValidationError("Posted purchase returns cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Purchase return {self.return_number} [{self.status}]"


class PurchaseReturnLine(TimeStampedUUIDModel):
    purchase_return = models.ForeignKey(
        PurchaseReturn, on_delete=models.CASCADE, related_name="lines"
    )
    invoice_line = models.ForeignKey(
        PurchaseInvoiceLine, on_delete=models.PROTECT, related_name="return_lines"
    )
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name="purchase_return_lines"
    )
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="purchase_return_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0), name="purchase_return_line_qty_positive"
            )
        ]

    def clean(self):
        super().clean()
        services.validate_return_line(self)

    def _guard_mutable(self):
        if self.purchase_return_id:
            status = (
                PurchaseReturn.objects.filter(pk=self.purchase_return_id)
                .values_list("status", flat=True)
                .first()
            )
            if status in _IMMUTABLE_STATUSES:
                raise ValidationError("Lines of a posted purchase return are immutable.")

    def save(self, *args, **kwargs):
        self._guard_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"Return {self.product.sku} x {self.quantity}"
