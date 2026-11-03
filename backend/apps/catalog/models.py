"""Catalog master data (Sprint 03).

Products, categories, units and unit conversions. Prices stored here are
*reference* prices (defaults for future sales/purchasing documents); the
accounting truth lives in journal lines and the inventory truth in stock
movements — never in these fields.
"""

from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.catalog import services
from apps.core.models import TimeStampedUUIDModel
from apps.organizations.models import Company


class Unit(TimeStampedUUIDModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="units")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_unit_code_per_company")
        ]

    def __str__(self):
        return f"{self.code} — {self.name}"


class ProductCategory(TimeStampedUUIDModel):
    company = models.ForeignKey(
        Company, on_delete=models.CASCADE, related_name="product_categories"
    )
    parent = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="children"
    )
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"], name="uniq_category_code_per_company"
            )
        ]

    def clean(self):
        super().clean()
        services.validate_category_hierarchy(self)

    def __str__(self):
        return f"{self.code} — {self.name}"


class Product(TimeStampedUUIDModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(
        ProductCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="products")
    sku = models.CharField(max_length=64)
    barcode = models.CharField(max_length=64, blank=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    is_stockable = models.BooleanField(default=True)  # False = service / non-stock item
    is_active = models.BooleanField(default=True)
    min_stock_level = models.DecimalField(max_digits=19, decimal_places=3, default=0)
    # Reference prices only — never used as accounting/inventory truth.
    default_purchase_price = models.DecimalField(
        max_digits=19, decimal_places=2, null=True, blank=True
    )
    default_sale_price = models.DecimalField(max_digits=19, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["sku"]
        constraints = [
            models.UniqueConstraint(fields=["company", "sku"], name="uniq_product_sku_per_company"),
            models.CheckConstraint(
                condition=models.Q(min_stock_level__gte=0), name="product_min_stock_non_negative"
            ),
        ]

    def clean(self):
        super().clean()
        if self.category_id and self.category.company_id != self.company_id:
            raise ValidationError(_("Product category belongs to a different company."))
        if self.base_unit_id and self.base_unit.company_id != self.company_id:
            raise ValidationError(_("Base unit belongs to a different company."))

    def __str__(self):
        return f"{self.sku} — {self.name}"


class ProductUnitConversion(TimeStampedUUIDModel):
    """``1 from_unit = factor * to_unit`` for one product.

    Conversions are product-scoped (a "box" means a product-specific number
    of base units), which is the only dimension-safe interpretation without
    a global unit-dimension model. Reverse conversion divides by the factor.
    """

    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="unit_conversions")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="unit_conversions")
    from_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="conversions_from")
    to_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="conversions_to")
    factor = models.DecimalField(max_digits=19, decimal_places=6)

    class Meta:
        ordering = ["product__sku", "from_unit__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "from_unit", "to_unit"],
                name="uniq_conversion_per_product_pair",
            ),
            models.CheckConstraint(
                condition=models.Q(factor__gt=0), name="conversion_factor_positive"
            ),
        ]

    def clean(self):
        super().clean()
        services.validate_conversion(self)

    def __str__(self):
        return f"{self.product.sku}: 1 {self.from_unit.code} = {self.factor} {self.to_unit.code}"
