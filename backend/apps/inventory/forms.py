"""Inventory forms (master data Sprint 12; stock counts Sprint 13)."""

from django import forms

from apps.catalog.models import Product, Unit
from apps.core.forms import date_widget
from apps.inventory.models import StockDocument, Warehouse
from apps.organizations.models import Company


class WarehouseForm(forms.ModelForm):
    class Meta:
        model = Warehouse
        fields = ["company", "code", "name", "is_active"]
        labels = {"company": "شرکت", "code": "کد انبار", "name": "نام انبار", "is_active": "فعال"}


class InventoryCountCreateForm(forms.Form):
    """Stock-count header (Sprint 13). The service snapshots every
    active stockable product of the company in the chosen warehouse;
    counted quantities are seeded with the snapshot and edited on the
    count page before posting."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none(), label="انبار")
    count_date = forms.DateField(
        widget=date_widget(),
        label="تاریخ شمارش",
        help_text="تاریخ به میلادی وارد می‌شود؛ نمایش تاریخ‌ها در سامانه جلالی است.",
    )
    description = forms.CharField(
        max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="شرح"
    )

    def __init__(self, *args, companies=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                company=company, is_active=True
            ).order_by("code")


class CountLineEditForm(forms.Form):
    """One count line on the count page: the counted quantity plus the
    optional unit cost used to value a positive variance of a product
    that has no stock (the service's adjustment rule)."""

    counted_qty = forms.DecimalField(max_digits=19, decimal_places=3, label="شمارش‌شده")
    unit_cost = forms.DecimalField(
        max_digits=19, decimal_places=6, required=False, label="بهای واحد (فقط کالای یافت‌شده)"
    )


CountLineFormSet = forms.formset_factory(CountLineEditForm, extra=0)


class CountPostForm(forms.Form):
    """Optional GL booking of the count's net variance (Sprint 13).

    Both accounts or neither: with neither, the count posts its stock
    adjustment only (GL is opt-in, ADR-013)."""

    inventory_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, required=False, label="حساب موجودی (دفتر کل)"
    )
    variance_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, required=False, label="حساب مغایرت انبارگردانی"
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            from apps.accounting.forms import eligible_accounts

            self.fields["inventory_account"].queryset = eligible_accounts(company, "ASSET")
            self.fields["variance_account"].queryset = eligible_accounts(company)

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("inventory_account")) != bool(cleaned.get("variance_account")):
            raise forms.ValidationError(
                "برای ثبت سند مغایرت، هر دو حساب موجودی و مغایرت را انتخاب کنید یا هیچ‌کدام را انتخاب نکنید."
            )
        return cleaned


class StockDocumentForm(forms.Form):
    """Stock-document header (Sprint 14). Document types are the
    service's: receipt, issue, transfer, adjustment. The purpose
    picker adds the Sprint 07 opening-stock recipe: "موجودی اول دوره"
    forces a receipt and stamps ``source_type="opening_stock"`` in
    the view."""

    PURPOSE_CHOICES = [
        ("NORMAL", "عادی"),
        ("OPENING_STOCK", "موجودی اول دوره"),
    ]

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    doc_type = forms.ChoiceField(
        choices=[
            (StockDocument.DocType.RECEIPT, "رسید (ورود)"),
            (StockDocument.DocType.ISSUE, "حواله (خروج)"),
            (StockDocument.DocType.TRANSFER, "انتقال بین انبارها"),
            (StockDocument.DocType.ADJUSTMENT, "تعدیل"),
        ],
        label="نوع سند",
    )
    purpose = forms.ChoiceField(choices=PURPOSE_CHOICES, initial="NORMAL", label="کاربرد سند")
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none(), label="انبار")
    destination_warehouse = forms.ModelChoiceField(
        queryset=Warehouse.objects.none(), required=False, label="انبار مقصد (فقط انتقال)"
    )
    doc_date = forms.DateField(
        widget=date_widget(),
        label="تاریخ سند",
        help_text="تاریخ به میلادی وارد می‌شود؛ نمایش تاریخ‌ها در سامانه جلالی است.",
    )
    description = forms.CharField(
        max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="شرح"
    )

    def __init__(self, *args, companies=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            warehouses = Warehouse.objects.filter(company=company, is_active=True).order_by("code")
            self.fields["warehouse"].queryset = warehouses
            self.fields["destination_warehouse"].queryset = warehouses


class StockDocumentLineForm(forms.Form):
    """One stock-document line. ``unit_cost`` is required by the
    service for receipts (and for positive adjustments of products
    without stock); issues and transfers are costed by MWAC."""

    product = forms.ModelChoiceField(queryset=Product.objects.none(), label="کالا")
    unit = forms.ModelChoiceField(queryset=Unit.objects.none(), required=False, label="واحد")
    quantity = forms.DecimalField(max_digits=19, decimal_places=3, label="مقدار")
    unit_cost = forms.DecimalField(
        max_digits=19, decimal_places=6, required=False, label="بهای واحد (رسید)"
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(
                company=company, is_active=True, is_stockable=True
            ).order_by("sku")
            self.fields["unit"].queryset = Unit.objects.filter(company=company).order_by("name")


StockDocumentLineFormSet = forms.formset_factory(
    StockDocumentLineForm, extra=3, can_delete=True, min_num=1, validate_min=True
)


class StockDocumentPostForm(forms.Form):
    """Optional GL booking on post (ADR-013): an inventory account
    and an offset account, both or neither. The service only books a
    journal for receipts and issues; transfers and adjustments move
    stock without a journal either way."""

    inventory_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, required=False, label="حساب موجودی (دفتر کل)"
    )
    offset_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, required=False, label="حساب طرف مقابل"
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            from apps.accounting.forms import eligible_accounts

            self.fields["inventory_account"].queryset = eligible_accounts(company, "ASSET")
            self.fields["offset_account"].queryset = eligible_accounts(company)

    def clean(self):
        cleaned = super().clean()
        if bool(cleaned.get("inventory_account")) != bool(cleaned.get("offset_account")):
            raise forms.ValidationError(
                "برای ثبت سند حسابداری، هر دو حساب موجودی و طرف مقابل را انتخاب کنید یا هیچ‌کدام را انتخاب نکنید."
            )
        return cleaned
