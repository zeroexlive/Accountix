from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.access import user_company_ids
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
