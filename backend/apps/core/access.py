"""Company-scoping helpers.

Views and services must never trust a company id from the client: they
resolve the set of companies the current user belongs to here and filter
every queryset by it.
"""

from django.core.exceptions import PermissionDenied


def user_company_ids(user) -> list:
    """Return company ids the user is an active member of."""
    if not user.is_authenticated:
        return []
    from apps.organizations.models import CompanyMembership

    return list(
        CompanyMembership.objects.filter(user=user, is_active=True).values_list(
            "company_id", flat=True
        )
    )


def require_company_access(user, company) -> None:
    if company.id not in user_company_ids(user):
        raise PermissionDenied("You are not a member of this company.")


def require_posted_company_member(request):
    """404 when a POST names a company outside the user's memberships.

    Master-data ModelForms narrow their company queryset (the Sprint
    01 pattern), which alone would turn a forged company id into a
    form error; the data-entry views additionally 404, matching the
    document create views (:func:`resolve_scoped_company`). No-op when
    the POST carries no company value.
    """
    from django.shortcuts import get_object_or_404

    raw = request.POST.get("company")
    if raw:
        get_object_or_404(member_companies(request.user), pk=raw)


def member_companies(user):
    """QuerySet of the companies the user is an active member of."""
    from apps.organizations.models import Company

    return Company.objects.filter(id__in=user_company_ids(user))


def resolve_scoped_company(request):
    """Resolve the single company a create form operates in (Sprint 12).

    Returns ``(companies, company)`` where ``companies`` is the member
    queryset and ``company`` is the selected company or ``None`` when
    the user belongs to several companies and has not chosen one yet.
    The selection comes from POST first, then GET (the create pages
    re-scope their pickers through a small GET chooser); a company id
    outside the user's memberships raises Http404, exactly like the
    detail views. When the user belongs to exactly one company it is
    selected automatically.
    """
    from django.shortcuts import get_object_or_404

    companies = member_companies(request.user)
    raw = request.POST.get("company") or request.GET.get("company")
    if raw:
        return companies, get_object_or_404(companies, pk=raw)
    if companies.count() == 1:
        return companies, companies.first()
    return companies, None
