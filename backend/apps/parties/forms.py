"""Party master-data forms (Sprint 12, ADR-039).

Master data follows the Sprint 01 pattern: ModelForms whose model
``clean()`` runs the service validation (``parties.services``,
ADR-002). Company choices are always narrowed to the user's
memberships server-side; on edit the company is fixed (a party must
not hop companies and orphan its subledger history).
"""

from django import forms
from django.forms import BaseInlineFormSet

from apps.parties.models import Party, PartyAddress, PartyContact

PARTY_LABELS = {
    "company": "شرکت",
    "kind": "نوع طرف‌حساب",
    "code": "کد",
    "name": "نام",
    "legal_name": "نام قانونی",
    "tax_id": "شناسه مالیاتی",
    "registration_number": "شماره ثبت",
    "email": "ایمیل",
    "phone": "تلفن",
    "is_active": "فعال",
}


class PartyForm(forms.ModelForm):
    class Meta:
        model = Party
        fields = [
            "company",
            "kind",
            "code",
            "name",
            "legal_name",
            "tax_id",
            "registration_number",
            "email",
            "phone",
            "is_active",
        ]
        labels = PARTY_LABELS


ContactFormSet: type[BaseInlineFormSet] = forms.inlineformset_factory(
    Party,
    PartyContact,
    fields=["full_name", "role", "phone", "email", "is_primary"],
    extra=1,
    can_delete=True,
)

AddressFormSet: type[BaseInlineFormSet] = forms.inlineformset_factory(
    Party,
    PartyAddress,
    fields=["label", "line1", "line2", "city", "province", "postal_code", "country"],
    extra=1,
    can_delete=True,
)
