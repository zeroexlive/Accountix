from django import forms
from django.utils.translation import gettext_lazy as _

from apps.organizations.models import Company, FiscalPeriod, FiscalYear


class FiscalCloseForm(forms.Form):
    """Retained-earnings picker for period/year closing (Sprint 13).

    ADR-028/011: the closing entry moves the period result into a
    retained-earnings account the *user* picks per closing — nothing
    is hardcoded. Eligibility is the Sprint 12 GL-picker rule (active,
    postable, same company), narrowed to EQUITY accounts.
    """

    retained_earnings: forms.ModelChoiceField = forms.ModelChoiceField(
        queryset=None, label=_("حساب سود (زیان) انباشته"), required=True
    )

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        from apps.accounting.forms import eligible_accounts

        if company is not None:
            self.fields["retained_earnings"].queryset = eligible_accounts(company, "EQUITY")


class CompanyForm(forms.ModelForm):
    class Meta:
        model = Company
        fields = ["name", "legal_name", "registration_number", "default_currency"]


class FiscalYearForm(forms.ModelForm):
    class Meta:
        model = FiscalYear
        fields = ["company", "name", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }


class FiscalPeriodForm(forms.ModelForm):
    class Meta:
        model = FiscalPeriod
        fields = ["company", "fiscal_year", "name", "start_date", "end_date", "status"]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }
