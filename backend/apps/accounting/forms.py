from django import forms

from apps.accounting.models import Account


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
