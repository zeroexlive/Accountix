"""Purchase data-entry forms (Sprint 12, ADR-039).

Forms collect input only: every create/post goes through
``purchases.services`` and every GL account is picked by the user per
document from the eligible accounts of the invoice's company
(ADR-011 — active + postable, narrowed by account type). Querysets
are scoped to the resolved company, so a forged cross-company id
fails form validation before the service ever sees it.
"""

from django import forms

from apps.accounting.forms import account_field
from apps.catalog.models import Product, Unit
from apps.core.forms import date_widget
from apps.inventory.models import Warehouse
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.purchases.models import PurchaseInvoiceLine


class PurchaseInvoiceForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    supplier = forms.ModelChoiceField(queryset=Party.objects.none(), label="تأمین‌کننده")
    invoice_number = forms.CharField(max_length=32, label="شماره فاکتور")
    invoice_date = forms.DateField(widget=date_widget(), label="تاریخ فاکتور")
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none(), label="انبار")
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="توضیحات"
    )

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["supplier"].queryset = Party.objects.filter(
                company=company, is_active=True, kind__in=[Party.Kind.SUPPLIER, Party.Kind.BOTH]
            ).order_by("code")
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                company=company, is_active=True
            ).order_by("code")


class PurchaseInvoiceLineForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), label="کالا")
    unit = forms.ModelChoiceField(queryset=Unit.objects.none(), required=False, label="واحد")
    quantity = forms.DecimalField(max_digits=19, decimal_places=3, label="مقدار")
    unit_cost = forms.DecimalField(max_digits=19, decimal_places=2, label="بهای واحد")
    discount_amount = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label="تخفیف"
    )
    tax_rate = forms.DecimalField(
        max_digits=9, decimal_places=4, required=False, initial=0, label="نرخ مالیات"
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["product"].queryset = Product.objects.filter(
                company=company, is_active=True
            ).order_by("sku")
            self.fields["unit"].queryset = Unit.objects.filter(
                company=company, is_active=True
            ).order_by("code")


PurchaseInvoiceLineFormSet = forms.formset_factory(
    PurchaseInvoiceLineForm, extra=3, can_delete=True
)


class PurchaseInvoicePostForm(forms.Form):
    """GL account pickers for posting a purchase invoice.

    Field requirement mirrors the service contract: payables is
    always required; inventory/expense/tax become required only when
    the invoice actually carries stockable lines, service lines or
    tax (the view computes that from the invoice totals)."""

    def __init__(self, *args, company, require=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payables"] = account_field(company, "LIABILITY", label="حساب پرداختنی")
        self.fields["inventory"] = account_field(
            company, "ASSET", required="inventory" in require, label="حساب موجودی کالا"
        )
        self.fields["expense"] = account_field(
            company, "EXPENSE", required="expense" in require, label="حساب هزینه / خدمات"
        )
        self.fields["tax"] = account_field(
            company, "ASSET", required="tax" in require, label="حساب مالیات خرید"
        )


class PurchaseReturnForm(forms.Form):
    return_number = forms.CharField(max_length=32, label="شماره برگشت")
    return_date = forms.DateField(widget=date_widget(), label="تاریخ برگشت")
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label="توضیحات"
    )


class PurchaseReturnLineForm(forms.Form):
    """One fixed row per original invoice line: only the quantity is
    editable; the line itself is carried in a hidden field."""

    invoice_line = forms.ModelChoiceField(
        queryset=PurchaseInvoiceLine.objects.none(), widget=forms.HiddenInput
    )
    quantity = forms.DecimalField(
        max_digits=19, decimal_places=3, required=False, initial=0, label="مقدار برگشتی"
    )

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        if invoice is not None:
            self.fields["invoice_line"].queryset = invoice.lines.all()


PurchaseReturnLineFormSet = forms.formset_factory(PurchaseReturnLineForm, extra=0)


class PurchaseReturnPostForm(forms.Form):
    """GL pickers for posting a return against a GL-posted invoice."""

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["payables"] = account_field(company, "LIABILITY", label="حساب پرداختنی")
        self.fields["inventory"] = account_field(company, "ASSET", label="حساب موجودی کالا")
