"""Template context for role-aware rendering (Sprint 25, ADR-050).

Server-side gates in the views are the security boundary; this
processor only feeds presentation: the shell shows the user's role in
their primary company, and list pages hide "new" buttons from users
who could not use them anywhere. Per-object pages resolve their own
company's role through the ``access_tags`` template tags.
"""

from config.version import __version__ as APP_VERSION

from apps.core.access import ADMINISTER_ROLES, OPERATE_ROLES


def app_version(request):
    """The product version (config/version.py — the one source of
    truth, Sprint 27 / ADR-052) for the shell footer and the login
    page; identical in source runs and the frozen bundle because the
    module ships inside the application package tree."""
    return {"app_version": APP_VERSION}


def tour_data(request):
    """Guided-tour payload for the current page (Sprint 30,
    ADR-057): the ``tour_payload`` context var the shell renders via
    ``json_script`` when the page's URL name has registered steps.
    Data-only (a dict lookup) — no queries."""
    from apps.core.tours import tour_payload

    match = getattr(request, "resolver_match", None)
    payload = tour_payload(match.url_name if match else None)
    return {"tour_payload": payload} if payload else {}


def company_roles(request):
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    from apps.organizations.models import CompanyMembership

    memberships = list(
        CompanyMembership.objects.filter(user=user, is_active=True)
        .select_related("company")
        .order_by("company__name")
    )
    roles = [m.role for m in memberships]
    return {
        "company_roles": {str(m.company_id): m.role for m in memberships},
        "primary_membership": memberships[0] if memberships else None,
        "can_operate_anywhere": any(role in OPERATE_ROLES for role in roles),
        "can_administer_anywhere": any(role in ADMINISTER_ROLES for role in roles),
    }
