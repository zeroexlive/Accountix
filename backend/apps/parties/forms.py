"""Party master-data forms (Sprint 12, ADR-039).

Master data follows the Sprint 01 pattern: ModelForms whose model
``clean()`` runs the service validation (``parties.services``,
ADR-002). Company choices are always narrowed to the user's
memberships server-side; on edit the company is fixed (a party must
not hop companies and orphan its subledger history).
"""

from django import forms
from django.forms import BaseInlineFormSet
from django.utils.translation import gettext_lazy as _

from apps.parties.models import Party, PartyAddress, PartyContact

PARTY_LABELS = {
    "company": _("شرکت"),
    "kind": _("نوع طرف‌حساب"),
    "code": _("کد"),
    "name": _("نام"),
    "legal_name": _("نام قانونی"),
    "tax_id": _("شناسه مالیاتی"),
    "registration_number": _("شماره ثبت"),
    "email": _("ایمیل"),
    "phone": _("تلفن"),
    "is_active": _("فعال"),
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
