from django import forms
from django.utils.translation import gettext_lazy as _

from apps.accounting.models import Account
from apps.core.forms import date_widget
from apps.organizations.models import Company
from apps.parties.models import Party


def eligible_accounts(company, account_type=None):
    """Accounts a document form may offer for ``company`` (Sprint 12).

    Eligible means active and postable, optionally narrowed to one
    account type (ADR-011: users pick accounts per document — there is
    no global mapping). The queryset is the server-side enforcement:
    a submitted id outside it fails form validation, and the posting
    services re-validate the company before anything is written.
    """
    qs = Account.objects.filter(company=company, is_active=True, is_postable=True)
    if account_type is not None:
        qs = qs.filter(account_type=account_type)
    return qs.order_by("code")


def account_field(company, account_type=None, *, required=True, label=""):
    """A ModelChoiceField over :func:`eligible_accounts`."""
    return forms.ModelChoiceField(
        queryset=eligible_accounts(company, account_type),
        required=required,
        label=label,
    )


class JournalEntryForm(forms.Form):
    """Manual journal entry header (Sprint 12). The idempotency key
    is pre-filled with a per-form token so an accidental double submit
    collides in the service instead of duplicating the draft; the
    user may replace it with their own key."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    entry_date = forms.DateField(widget=date_widget(), label=_("تاریخ سند"))
    description = forms.CharField(
        max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label=_("شرح سند")
    )
    idempotency_key = forms.CharField(
        max_length=100,
        required=False,
        label=_("کلید یکتایی (اختیاری)"),
        help_text=_("برای جلوگیری از ثبت تکراری یک سند؛ خالی بماند، سامانه کلید می‌سازد."),
    )

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies


class JournalLineForm(forms.Form):
    """One journal line. Amounts stay optional at the form layer on
    purpose: the one-sided/balanced rules are §6.3 service rules and
    their messages must reach the user verbatim (ADR-039)."""

    account = forms.ModelChoiceField(queryset=Account.objects.none(), label=_("حساب"))
    debit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label=_("بدهکار")
    )
    credit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label=_("بستانکار")
    )
    description = forms.CharField(max_length=500, required=False, label=_("شرح"))
    party = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label=_("طرف‌حساب (برچسب فرعی)")
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["account"].queryset = eligible_accounts(company)
            self.fields["party"].queryset = Party.objects.filter(
                company=company, is_active=True
            ).order_by("code")


JournalLineFormSet = forms.formset_factory(JournalLineForm, extra=4, can_delete=True)


class OpeningBalanceForm(forms.Form):
    """Opening-balance header (Sprint 13). The offset account is the
    ADR-029 caller-supplied equity account: the service appends the
    difference to it, so the entry balances by construction."""

    company = forms.ModelChoiceField(
        queryset=Company.objects.none(), widget=forms.HiddenInput, label=_("شرکت")
    )
    fiscal_year: forms.ModelChoiceField = forms.ModelChoiceField(queryset=None, label=_("سال مالی"))
    offset_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, label=_("حساب طرف تراز افتتاحیه")
    )

    def __init__(self, *args, companies=None, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies
        if company is not None:
            from apps.organizations.models import FiscalYear

            self.fields["fiscal_year"].queryset = FiscalYear.objects.filter(
                company=company
            ).order_by("start_date")
            self.fields["offset_account"].queryset = eligible_accounts(company, "EQUITY")


class OpeningLineForm(forms.Form):
    """One opening-balance line: a single-sided amount on a postable
    account, optionally tagged with a party (opening AR/AP)."""

    account = forms.ModelChoiceField(queryset=Account.objects.none(), label=_("حساب"))
    debit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label=_("بدهکار")
    )
    credit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label=_("بستانکار")
    )
    party = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label=_("طرف‌حساب (برچسب فرعی)")
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company is not None:
            self.fields["account"].queryset = eligible_accounts(company)
            self.fields["party"].queryset = Party.objects.filter(
                company=company, is_active=True
            ).order_by("code")


OpeningLineFormSet = forms.formset_factory(OpeningLineForm, extra=4, can_delete=True)


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "company",
            "parent",
            "code",
            "name",
            "account_type",
            "normal_balance",
            "is_postable",
            "is_active",
        ]
        # Explicit labels (Sprint 30, ADR-055): the Account model has
        # no verbose_names, so without this dict Django auto-generates
        # English labels from the field names and they render verbatim
        # in the Persian UI — the Sprint 20 sweep only covered forms
        # that defined their labels.
        labels = {
            "company": _("شرکت"),
            "parent": _("حساب والد"),
            "code": _("کد"),
            "name": _("نام"),
            "account_type": _("نوع حساب"),
            "normal_balance": _("ماهیت"),
            "is_postable": _("قابل ثبت"),
            "is_active": _("فعال"),
        }
