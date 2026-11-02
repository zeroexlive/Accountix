from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render

from apps.core.access import user_company_ids
from apps.organizations.models import Company


def health(request):
    return JsonResponse({"status": "ok"})


@login_required
def dashboard(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user), is_active=True)
    return render(request, "core/dashboard.html", {"companies": companies})
