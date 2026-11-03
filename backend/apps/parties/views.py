from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.access import member_companies, require_posted_company_member, user_company_ids
from apps.parties.forms import AddressFormSet, ContactFormSet, PartyForm
from apps.parties.models import Party


@login_required
def party_list(request):
    parties = (
        Party.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company")
        .prefetch_related("contacts", "addresses")
        .order_by("code")
    )
    return render(request, "parties/party_list.html", {"parties": parties})


@login_required
def party_detail(request, pk):
    party = get_object_or_404(
        Party.objects.select_related("company").prefetch_related("contacts", "addresses"),
        pk=pk,
        company_id__in=user_company_ids(request.user),
    )
    return render(request, "parties/party_detail.html", {"party": party})


def _party_form_page(request, party=None):
    """Shared create/edit handling: the party form plus its contact and
    address inline formsets, all validated before anything is saved."""
    is_edit = party is not None
    if request.method == "POST" and not is_edit:
        # Same rule as the document create views: a company id outside
        # the user's memberships is a 404, not a form error.
        require_posted_company_member(request)
    form = PartyForm(request.POST or None, instance=party)
    form.fields["company"].queryset = member_companies(request.user)
    if is_edit:
        form.fields["company"].disabled = True
    blank = party if is_edit else Party()
    contacts = ContactFormSet(request.POST or None, instance=blank, prefix="contacts")
    addresses = AddressFormSet(request.POST or None, instance=blank, prefix="addresses")
    if (
        request.method == "POST"
        and form.is_valid()
        and contacts.is_valid()
        and addresses.is_valid()
    ):
        party = form.save()
        contacts.instance = party
        contacts.save()
        addresses.instance = party
        addresses.save()
        messages.success(request, _("طرف‌حساب ذخیره شد."))
        return redirect("party_detail", pk=party.pk)
    return render(
        request,
        "parties/party_form.html",
        {"form": form, "contacts": contacts, "addresses": addresses, "party": party},
    )


@login_required
def party_create(request):
    return _party_form_page(request)


@login_required
def party_edit(request, pk):
    party = get_object_or_404(Party, pk=pk, company_id__in=user_company_ids(request.user))
    return _party_form_page(request, party)
