from django import forms

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
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    entry_date = forms.DateField(widget=date_widget(), label="تاریخ سند")
    description = forms.CharField(
        max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), label="شرح سند"
    )
    idempotency_key = forms.CharField(
        max_length=100,
        required=False,
        label="کلید یکتایی (اختیاری)",
        help_text="برای جلوگیری از ثبت تکراری یک سند؛ خالی بماند، سامانه کلید می‌سازد.",
    )

    def __init__(self, *args, companies=None, **kwargs):
        super().__init__(*args, **kwargs)
        if companies is not None:
            self.fields["company"].queryset = companies


class JournalLineForm(forms.Form):
    """One journal line. Amounts stay optional at the form layer on
    purpose: the one-sided/balanced rules are §6.3 service rules and
    their messages must reach the user verbatim (ADR-039)."""

    account = forms.ModelChoiceField(queryset=Account.objects.none(), label="حساب")
    debit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label="بدهکار"
    )
    credit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label="بستانکار"
    )
    description = forms.CharField(max_length=500, required=False, label="شرح")
    party = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label="طرف‌حساب (برچسب فرعی)"
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
        queryset=Company.objects.none(), widget=forms.HiddenInput, label="شرکت"
    )
    fiscal_year: forms.ModelChoiceField = forms.ModelChoiceField(queryset=None, label="سال مالی")
    offset_account: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, label="حساب طرف تراز افتتاحیه"
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

    account = forms.ModelChoiceField(queryset=Account.objects.none(), label="حساب")
    debit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label="بدهکار"
    )
    credit = forms.DecimalField(
        max_digits=19, decimal_places=2, required=False, initial=0, label="بستانکار"
    )
    party = forms.ModelChoiceField(
        queryset=Party.objects.none(), required=False, label="طرف‌حساب (برچسب فرعی)"
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
