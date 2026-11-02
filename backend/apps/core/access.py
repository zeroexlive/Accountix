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
