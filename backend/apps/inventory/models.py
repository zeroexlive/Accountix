"""Inventory ledger models (Sprint 03).

``StockMovement`` is the authoritative record — append-only, never edited
or deleted. There is deliberately **no** ``StockBalance`` table: balances
are derived from movements in ``apps.inventory.reporting`` (ADR-012),
exactly as accounting balances are derived from journal lines.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.catalog.models import Product, Unit
from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company


class Warehouse(TimeStampedUUIDModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="warehouses")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_warehouse_code_per_company"
            )
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


_IMMUTABLE_DOC_STATUSES = ("POSTED", "REVERSED")
_DOC_MUTABLE_FIELDS = {
    "id",
    "created_at",
    "updated_at",
    "company_id",
    "warehouse_id",
    "destination_warehouse_id",
    "doc_type",
    "doc_date",
    "description",
    "status",
    "source_type",
    "source_id",
    "reversal_of_id",
    "journal_entry_id",
    "posted_by_id",
    "posted_at",
}


class StockDocument(TimeStampedUUIDModel):
    """Stock document header. ``warehouse`` is the primary warehouse; for a
    TRANSFER it is the source and ``destination_warehouse`` the target."""

    class DocType(models.TextChoices):
        RECEIPT = "RECEIPT", "Receipt"
        ISSUE = "ISSUE", "Issue"
        TRANSFER = "TRANSFER", "Transfer"
        ADJUSTMENT = "ADJUSTMENT", "Adjustment"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        POSTED = "POSTED", "Posted"
        REVERSED = "REVERSED", "Reversed"

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="stock_documents")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="stock_documents"
    )
    destination_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="stock_documents_in",
    )
    doc_type = models.CharField(max_length=10, choices=DocType.choices)
    doc_date = models.DateField()
    description = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    # Free source reference (e.g. PURCHASE_INVOICE / id) like JournalEntry;
    # parties are deferred — see ADR-014.
    source_type = models.CharField(max_length=50, blank=True)
    source_id = models.CharField(max_length=64, blank=True)
    reversal_of = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reversal_documents",
    )
    journal_entry = models.ForeignKey(
        "accounting.JournalEntry",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_documents",
    )
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posted_stock_documents",
    )
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["doc_date", "created_at"]

    @property
    def is_reversal(self) -> bool:
        return self.reversal_of_id is not None

    def save(self, *args, **kwargs):
        if self.pk:
            old = StockDocument.objects.filter(pk=self.pk).first()
            if old is not None and old.status in _IMMUTABLE_DOC_STATUSES:
                allowed = (
                    old.status == "POSTED"
                    and self.status == "REVERSED"
                    and all(
                        getattr(old, f) == getattr(self, f)
                        for f in _DOC_MUTABLE_FIELDS - {"status"}
                    )
                )
                if not allowed:
                    raise ValidationError(
                        "Posted stock documents are immutable; reverse the document instead."
                    )
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.status in _IMMUTABLE_DOC_STATUSES:
            raise ValidationError("Posted stock documents cannot be deleted.")
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.doc_type} {self.doc_date} [{self.status}]"


class StockDocumentLine(TimeStampedUUIDModel):
    """One product line. ``quantity`` is expressed in ``unit`` (default: the
    product's base unit) and is positive for RECEIPT/ISSUE/TRANSFER; for
    ADJUSTMENT it is signed (its sign is the adjustment direction).
    ``unit_cost`` is required by the service for receipts/positive
    adjustments when no average exists, and ignored for issues (valued at
    the moving average)."""

    document = models.ForeignKey(StockDocument, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_lines")
    unit = models.ForeignKey(
        Unit, on_delete=models.PROTECT, null=True, blank=True, related_name="stock_lines"
    )
    quantity = models.DecimalField(max_digits=19, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(quantity=0), name="stock_line_quantity_non_zero"
            )
        ]

    def _guard_mutable(self):
        if self.document_id:
            status = (
                StockDocument.objects.filter(pk=self.document_id)
                .values_list("status", flat=True)
                .first()
            )
            if status in _IMMUTABLE_DOC_STATUSES:
                raise ValidationError("Lines of a posted stock document are immutable.")

    def save(self, *args, **kwargs):
        self._guard_mutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        self._guard_mutable()
        return super().delete(*args, **kwargs)

    def __str__(self):
        return f"{self.product.sku} x {self.quantity}"


class StockMovement(TimeStampedUUIDModel):
    """Append-only stock ledger entry — the single source of truth.

    Quantities are always in the product's base unit. ``value_delta`` is
    signed like ``quantity_delta``. ``unit_cost`` is the moving weighted
    average (receipts: the receipt cost) at the moment of the movement.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="stock_movements")
    warehouse = models.ForeignKey(
        Warehouse, on_delete=models.PROTECT, related_name="stock_movements"
    )
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="stock_movements")
    quantity_delta = models.DecimalField(max_digits=19, decimal_places=3)
    unit_cost = models.DecimalField(max_digits=19, decimal_places=4, default=0)
    value_delta = models.DecimalField(max_digits=19, decimal_places=2, default=0)
    movement_date = models.DateField()
    document = models.ForeignKey(StockDocument, on_delete=models.PROTECT, related_name="movements")
    document_line = models.ForeignKey(
        StockDocumentLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movements",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    class Meta:
        ordering = ["movement_date", "created_at"]
        indexes = [
            models.Index(fields=["company", "warehouse", "product"], name="idx_movement_wh_product")
        ]

    def save(self, *args, **kwargs):
        if self.pk and StockMovement.objects.filter(pk=self.pk).exists():
            raise ValidationError("Stock movements are append-only and cannot be modified.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Stock movements are append-only and cannot be deleted.")

    def __str__(self):
        return f"{self.product.sku} {self.quantity_delta} @ {self.warehouse.code}"


class StockDocumentReversal(TimeStampedUUIDModel):
    """Dedicated reversal record, mirroring JournalReversal (ADR-009 pattern)."""

    original_document = models.OneToOneField(
        StockDocument, on_delete=models.PROTECT, related_name="reversal_record"
    )
    reversal_document = models.OneToOneField(
        StockDocument, on_delete=models.PROTECT, related_name="reversal_record_of"
    )
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_reversals",
    )
    reason = models.CharField(max_length=500, blank=True)
    reversed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reversal of {self.original_document_id}"
