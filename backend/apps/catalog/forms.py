"""Catalog master-data forms (Sprint 12, ADR-039).

ModelForms in the Sprint 01 pattern: the models' ``clean()`` methods
run the catalog services' cross-record validation (category hierarchy,
product company consistency), so a cross-company category or unit is
rejected server-side even before the posting services would see it.
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.catalog.models import Product, ProductCategory, Unit


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["company", "code", "name", "is_active"]
        labels = {
            "company": _("شرکت"),
            "code": _("کد واحد"),
            "name": _("نام واحد"),
            "is_active": _("فعال"),
        }


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["company", "parent", "code", "name", "is_active"]
        labels = {
            "company": _("شرکت"),
            "parent": _("دسته والد"),
            "code": _("کد دسته"),
            "name": _("نام دسته"),
            "is_active": _("فعال"),
        }


class ProductForm(forms.ModelForm):
    """Product create/edit. Pass ``company`` to scope the category and
    base-unit pickers to that company; the model ``clean()`` remains
    the final guard against cross-company picks."""

    class Meta:
        model = Product
        fields = [
            "company",
            "category",
            "base_unit",
            "sku",
            "barcode",
            "name",
            "description",
            "is_stockable",
            "is_active",
            "min_stock_level",
            "default_purchase_price",
            "default_sale_price",
        ]
        labels = {
            "company": _("شرکت"),
            "category": _("دسته‌بندی"),
            "base_unit": _("واحد پایه"),
            "sku": _("کد کالا (SKU)"),
            "barcode": _("بارکد"),
            "name": _("نام کالا"),
            "description": _("توضیحات"),
            "is_stockable": _("قابل انبارش"),
            "is_active": _("فعال"),
            "min_stock_level": _("حداقل موجودی"),
            "default_purchase_price": _("قیمت خرید پیش‌فرض"),
            "default_sale_price": _("قیمت فروش پیش‌فرض"),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["category"].queryset = ProductCategory.objects.filter(
                company=company
            ).order_by("code")
            self.fields["base_unit"].queryset = Unit.objects.filter(company=company).order_by(
                "code"
            )
