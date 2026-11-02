from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.core.access import user_company_ids
from apps.core.pagination import apply_date_range, paginate
from apps.treasury import reporting
from apps.treasury.models import Cheque, Payment, TreasuryAccount


@login_required
def treasury_account_list(request):
    accounts = TreasuryAccount.objects.filter(
        company_id__in=user_company_ids(request.user)
    ).select_related("company", "gl_account")
    rows = [
        {
            "account": account,
            "balance": reporting.treasury_account_balance(account.company, account),
        }
        for account in accounts
    ]
    return render(request, "treasury/account_list.html", {"rows": rows})


@login_required
def payment_list(request):
    payments = (
        Payment.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "party", "treasury_account")
        .order_by("-payment_date", "-created_at")
    )
    if request.GET.get("status"):
        payments = payments.filter(status=request.GET["status"])
    if request.GET.get("method"):
        payments = payments.filter(method=request.GET["method"])
    payments = apply_date_range(payments, request.GET, "payment_date")
    page_obj, filter_query = paginate(request, payments)
    return render(
        request,
        "treasury/payment_list.html",
        {
            "payments": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Payment.Status.choices,
            "methods": Payment.Method.choices,
        },
    )


@login_required
def cheque_list(request):
    cheques = (
        Cheque.objects.filter(company_id__in=user_company_ids(request.user))
        .select_related("company", "payment__party")
        .order_by("due_date")
    )
    if request.GET.get("status"):
        cheques = cheques.filter(status=request.GET["status"])
    if request.GET.get("direction"):
        cheques = cheques.filter(direction=request.GET["direction"])
    cheques = apply_date_range(cheques, request.GET, "due_date")
    # apply_date_range uses date_from/date_to on due_date; treasury uses it as due range.
    page_obj, filter_query = paginate(request, cheques)
    return render(
        request,
        "treasury/cheque_list.html",
        {
            "cheques": page_obj,
            "page_obj": page_obj,
            "filter_query": filter_query,
            "statuses": Cheque.Status.choices,
            "directions": Cheque.Direction.choices,
        },
    )


@login_required
def open_items_view(request):
    from apps.organizations.models import Company

    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    items = []
    for company in companies:
        items.extend(reporting.open_items(company))
    return render(request, "treasury/open_items.html", {"items": items})
