"""Sales data-entry forms (Sprint 12, ADR-039).

Mirror of the purchase forms: forms collect input only, every
create/post goes through ``sales.services``, and every GL account is
picked per document from the company's eligible accounts (ADR-011).
"""

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounting.forms import account_field
from apps.catalog.models import Product, Unit
from apps.core.forms import date_widget
from apps.inventory.models import Warehouse
from apps.organizations.models import Company
from apps.parties.models import Party
from apps.sales.models import SalesInvoiceLine


class SalesInvoiceForm(forms.Form):
    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    customer = forms.ModelChoiceField(queryset=Party.objects.none(), label=_("مشتری"))
    invoice_number = forms.CharField(max_length=32, label=_("شماره فاکتور"))
    invoice_date = forms.DateField(widget=date_widget(), label=_("تاریخ فاکتور"))
    warehouse = forms.ModelChoiceField(queryset=Warehouse.objects.none(), label=_("انبار"))
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("توضیحات")
    )

    def __init__(self, *args, company=None, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            self.fields["customer"].queryset = Party.objects.filter(
                company=company, is_active=True, kind__in=[Party.Kind.CUSTOMER, Party.Kind.BOTH]
            ).order_by("code")
            self.fields["warehouse"].queryset = Warehouse.objects.filter(
                company=company, is_active=True
            ).order_by("code")


class SalesInvoiceLineForm(forms.Form):
    product = forms.ModelChoiceField(queryset=Product.objects.none(), label=_("کالا"))
    unit = forms.ModelChoiceField(queryset=Unit.objects.none(), required=False, label=_("واحد"))
    quantity = forms.DecimalField(max_digits=19, decimal_places=3, label=_("مقدار"))
    unit_price = forms.DecimalField(max_digits=19, decimal_places=2, label=_("قیمت واحد"))
    discount_amount = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label=_("تخفیف")
    )
    tax_rate = forms.DecimalField(
        max_digits=9, decimal_places=4, required=False, initial=0, label=_("نرخ مالیات")
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


SalesInvoiceLineFormSet = forms.formset_factory(SalesInvoiceLineForm, extra=3, can_delete=True)


class SalesInvoicePostForm(forms.Form):
    """GL account pickers for posting a sales invoice (ADR-020):
    receivables always; revenue when there is a net sale; tax payable
    when tax is charged; COGS + inventory when stockable lines exist."""

    def __init__(self, *args, company, require=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["receivables"] = account_field(company, "ASSET", label=_("حساب دریافتنی"))
        self.fields["revenue"] = account_field(
            company, "REVENUE", required="revenue" in require, label=_("حساب درآمد فروش")
        )
        self.fields["tax_payable"] = account_field(
            company, "LIABILITY", required="tax_payable" in require, label=_("حساب مالیات فروش")
        )
        self.fields["cogs"] = account_field(
            company, "EXPENSE", required="cogs" in require, label=_("حساب بهای تمام‌شده")
        )
        self.fields["inventory"] = account_field(
            company, "ASSET", required="inventory" in require, label=_("حساب موجودی کالا")
        )


class SalesReturnForm(forms.Form):
    return_number = forms.CharField(max_length=32, label=_("شماره برگشت"))
    return_date = forms.DateField(widget=date_widget(), label=_("تاریخ برگشت"))
    description = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("توضیحات")
    )


class SalesReturnLineForm(forms.Form):
    """One fixed row per original invoice line (quantity only)."""

    invoice_line = forms.ModelChoiceField(
        queryset=SalesInvoiceLine.objects.none(), widget=forms.HiddenInput
    )
    quantity = forms.DecimalField(
        max_digits=19, decimal_places=3, required=False, initial=0, label=_("مقدار برگشتی")
    )

    def __init__(self, *args, invoice=None, **kwargs):
        super().__init__(*args, **kwargs)
        if invoice is not None:
            self.fields["invoice_line"].queryset = invoice.lines.all()


SalesReturnLineFormSet = forms.formset_factory(SalesReturnLineForm, extra=0)


class SalesReturnPostForm(forms.Form):
    """GL pickers for posting a return against a GL-posted invoice.
    Receivables and revenue are always required by the service then;
    tax/inventory/COGS depend on the return's shares, so the service
    validates them and its errors surface on this form."""

    def __init__(self, *args, company, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["receivables"] = account_field(company, "ASSET", label=_("حساب دریافتنی"))
        self.fields["revenue"] = account_field(company, "REVENUE", label=_("حساب درآمد فروش"))
        self.fields["tax_payable"] = account_field(
            company, "LIABILITY", required=False, label=_("حساب مالیات فروش")
        )
        self.fields["inventory"] = account_field(
            company, "ASSET", required=False, label=_("حساب موجودی کالا")
        )
        self.fields["cogs"] = account_field(
            company, "EXPENSE", required=False, label=_("حساب بهای تمام‌شده")
        )
