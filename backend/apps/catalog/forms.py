"""Catalog master-data forms (Sprint 12, ADR-039).

ModelForms in the Sprint 01 pattern: the models' ``clean()`` methods
run the catalog services' cross-record validation (category hierarchy,
product company consistency), so a cross-company category or unit is
rejected server-side even before the posting services would see it.
"""

from django import forms

from apps.catalog.models import Product, ProductCategory, Unit


class UnitForm(forms.ModelForm):
    class Meta:
        model = Unit
        fields = ["company", "code", "name", "is_active"]
        labels = {"company": "شرکت", "code": "کد واحد", "name": "نام واحد", "is_active": "فعال"}


class ProductCategoryForm(forms.ModelForm):
    class Meta:
        model = ProductCategory
        fields = ["company", "parent", "code", "name", "is_active"]
        labels = {
            "company": "شرکت",
            "parent": "دسته والد",
            "code": "کد دسته",
            "name": "نام دسته",
            "is_active": "فعال",
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
            "company": "شرکت",
            "category": "دسته‌بندی",
            "base_unit": "واحد پایه",
            "sku": "کد کالا (SKU)",
            "barcode": "بارکد",
            "name": "نام کالا",
            "description": "توضیحات",
            "is_stockable": "قابل انبارش",
            "is_active": "فعال",
            "min_stock_level": "حداقل موجودی",
            "default_purchase_price": "قیمت خرید پیش‌فرض",
            "default_sale_price": "قیمت فروش پیش‌فرض",
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
