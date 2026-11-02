from django import forms

from apps.organizations.models import Company, FiscalPeriod, FiscalYear


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
