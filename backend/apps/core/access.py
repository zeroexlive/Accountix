"""Company-scoping helpers.

Views and services must never trust a company id from the client: they
resolve the set of companies the current user belongs to here and filter
every queryset by it.

Sprint 25 (ADR-050) adds role enforcement on top of membership: the
role tiers below partition ``CompanyMembership.Role`` into the
operation classes the views gate on. Membership alone still governs
every read; a mutating endpoint additionally requires the membership's
role to sit in the endpoint's tier.
"""

from functools import wraps

from django.core.exceptions import PermissionDenied

# Role tiers (ADR-050). The values are CompanyMembership.Role members,
# spelled out here so this module stays import-cycle free; a unit test
# pins the tiers against the model's choices so the two cannot drift.
READ_ROLES = (
    "OWNER",
    "ADMIN",
    "ACCOUNTANT",
    "SALES",
    "PURCHASES",
    "WAREHOUSE",
    "CASHIER",
    "VIEWER",
)
OPERATE_ROLES = (
    "OWNER",
    "ADMIN",
    "ACCOUNTANT",
    "SALES",
    "PURCHASES",
    "WAREHOUSE",
    "CASHIER",
)
ADMINISTER_ROLES = ("OWNER", "ADMIN")
GOVERN_ROLES = ("OWNER",)


def membership_for(user, company):
    """The user's ACTIVE membership in ``company``, or None.

    Cached on the user instance: a request typically resolves the same
    (user, company) pair in the view gate, the context processor and
    template tags, and the user object lives exactly one request.
    """
    if user is None or company is None or not getattr(user, "is_authenticated", False):
        return None
    cache = getattr(user, "_membership_cache", None)
    if cache is None:
        cache = {}
        user._membership_cache = cache
    key = company.pk
    if key not in cache:
        from apps.organizations.models import CompanyMembership

        cache[key] = (
            CompanyMembership.objects.filter(user=user, company=company, is_active=True)
            .select_related("company")
            .first()
        )
    return cache[key]


def role_for(user, company):
    """The user's role value in ``company`` (None when not a member)."""
    membership = membership_for(user, company)
    return membership.role if membership is not None else None


def require_company_role(user, company, roles) -> None:
    """403 unless the user's role in ``company`` is one of ``roles``.

    Callers resolve membership first (their scoped querysets 404 for
    non-members), so a PermissionDenied from here always means "member
    with an insufficient role" — never an existence leak.
    """
    if role_for(user, company) not in roles:
        raise PermissionDenied("Your role in this company does not allow this operation.")


def require_posted_company_role(request, roles) -> None:
    """Posted-company variant for master-data form views (ADR-050).

    When the POST names a company: 404 when it sits outside the user's
    memberships (the standing Sprint 12 rule), then 403 when the
    member's role is below ``roles``. No-op when the POST carries no
    company value.
    """
    from django.shortcuts import get_object_or_404

    raw = request.POST.get("company")
    if raw:
        company = get_object_or_404(member_companies(request.user), pk=raw)
        require_company_role(request.user, company, roles)


def scoped_company_role_required(*roles):
    """Decorator for create views built on :func:`resolve_scoped_company`.

    Resolves the company exactly the way the wrapped view will (POST,
    then GET, then the single-membership default; a foreign id 404s
    inside the resolver) and requires ``roles`` on it before the view
    runs. When no company is resolved yet (a multi-company user has
    not chosen one) there is nothing to gate — the view can only
    render its chooser, because every save path in these views is
    guarded by ``company is not None``.
    """

    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            _companies, company = resolve_scoped_company(request)
            if company is not None:
                require_company_role(request.user, company, roles)
            return view(request, *args, **kwargs)

        return wrapper

    return decorator


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
