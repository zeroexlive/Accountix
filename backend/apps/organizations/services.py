"""Application services for organization / fiscal rules.

Validation that spans records (overlaps) lives here, not in views, so the
same rules apply to forms, the API and future importers.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.translation import gettext_lazy as _


def validate_date_range(start, end, *, start_label="Start date", end_label="End date"):
    if start and end and start > end:
        raise ValidationError(
            _("%(start_label)s must be on or before %(end_label)s.")
            % {"start_label": start_label, "end_label": end_label}
        )


def fiscal_years_overlap(company_id, start, end, *, exclude_id=None) -> bool:
    from apps.organizations.models import FiscalYear

    qs = FiscalYear.objects.filter(company_id=company_id, start_date__lte=end, end_date__gte=start)
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


def fiscal_periods_overlap(fiscal_year_id, start, end, *, exclude_id=None) -> bool:
    from apps.organizations.models import FiscalPeriod

    qs = FiscalPeriod.objects.filter(
        fiscal_year_id=fiscal_year_id, start_date__lte=end, end_date__gte=start
    )
    if exclude_id:
        qs = qs.exclude(pk=exclude_id)
    return qs.exists()


# ---------------------------------------------------------------------------
# Membership management (Sprint 26, ADR-051)
# ---------------------------------------------------------------------------


def _require_govern_role(company, actor) -> None:
    """Defense-in-depth for the GOVERN-tier services (ADR-051).

    The members views gate at the GOVERN tier; the services repeat
    the assertion whenever an actor is supplied, mirroring
    accounting's ``_require_administer_role`` (ADR-050 (3)).
    ``actor=None`` marks a trusted internal call and skips the
    check. A PermissionDenied — not a ValidationError — propagates:
    this is an authorization stop, not form feedback.
    """
    if actor is None:
        return
    from apps.core.access import GOVERN_ROLES, require_company_role

    require_company_role(actor, company, GOVERN_ROLES)


def _validate_role(role) -> None:
    from apps.organizations.models import CompanyMembership

    if role not in CompanyMembership.Role.values:
        raise ValidationError(_("Invalid role."))


def _active_owner_count(company, *, exclude_id=None) -> int:
    from apps.organizations.models import CompanyMembership

    qs = CompanyMembership.objects.filter(
        company=company, role=CompanyMembership.Role.OWNER, is_active=True
    )
    if exclude_id is not None:
        qs = qs.exclude(pk=exclude_id)
    return qs.count()


def _guard_not_last_owner(membership) -> None:
    """Refuse to strip the company's final ACTIVE owner (ADR-051).

    Demoting or deactivating the sole remaining active OWNER would
    leave the company with nobody able to govern it, so every
    other-owner count runs *excluding* this membership — the guard
    applies equally when the actor targets themselves, and lifts as
    soon as a second active owner exists.
    """
    from apps.organizations.models import CompanyMembership

    if (
        membership.is_active
        and membership.role == CompanyMembership.Role.OWNER
        and _active_owner_count(membership.company, exclude_id=membership.pk) == 0
    ):
        raise ValidationError(
            _("The last active owner of a company cannot be demoted or deactivated.")
        )


@transaction.atomic
def add_member(*, actor, company, user, role):
    """Attach an existing user to a company with ``role`` (ADR-051).

    An existing membership row — active or deactivated — is a
    ValidationError, never an IntegrityError leak: a deactivated
    member comes back through :func:`reactivate_member`, not by
    re-adding.
    """
    from apps.organizations.models import CompanyMembership

    _require_govern_role(company, actor)
    _validate_role(role)
    if CompanyMembership.objects.filter(company=company, user=user).exists():
        raise ValidationError(_("This user is already a member of this company."))
    return CompanyMembership.objects.create(company=company, user=user, role=role)


@transaction.atomic
def create_member(*, actor, company, username, password, role, first_name="", last_name=""):
    """Create a NEW user and attach them to ``company``, atomically
    (ADR-051). The caller (the members form) has already run the
    username-uniqueness check and the full AUTH_PASSWORD_VALIDATORS
    set through UserCreationForm — the Sprint 24 setup pattern — so
    a weak password or a taken username never reaches here from the
    UI. No staff/superuser flags are granted: product authority is
    the membership alone, and the new user can log in immediately.
    """
    from django.contrib.auth import get_user_model

    from apps.organizations.models import CompanyMembership

    _require_govern_role(company, actor)
    _validate_role(role)
    user = get_user_model().objects.create_user(
        username=username, password=password, first_name=first_name, last_name=last_name
    )
    return CompanyMembership.objects.create(company=company, user=user, role=role)


@transaction.atomic
def change_member_role(*, actor, membership, new_role):
    """Change a membership's role, effective immediately (ADR-051).

    Enforcement resolves roles per request from the membership row,
    so the new role governs the member's very next request. The
    last-owner guard refuses to demote the final active OWNER.
    """
    _require_govern_role(membership.company, actor)
    _validate_role(new_role)
    if new_role != membership.role:
        _guard_not_last_owner(membership)
        membership.role = new_role
        membership.save(update_fields=["role", "updated_at"])
    return membership


@transaction.atomic
def deactivate_member(*, actor, membership):
    """Deactivate a membership — the removal path (ADR-051).

    There is no hard delete: the row stays for history and audit,
    and because every scoped queryset and role lookup only sees
    ACTIVE memberships, deactivation cuts the user's access to the
    company immediately. The last-owner guard applies.
    """
    _require_govern_role(membership.company, actor)
    if membership.is_active:
        _guard_not_last_owner(membership)
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
    return membership


@transaction.atomic
def reactivate_member(*, actor, membership):
    """Restore a deactivated membership with its previous role."""
    _require_govern_role(membership.company, actor)
    if not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
    return membership


def validate_fiscal_year(instance) -> None:
    validate_date_range(instance.start_date, instance.end_date)
    if (
        instance.start_date
        and instance.end_date
        and fiscal_years_overlap(
            instance.company_id, instance.start_date, instance.end_date, exclude_id=instance.pk
        )
    ):
        raise ValidationError(_("Fiscal year overlaps an existing fiscal year for this company."))


def validate_fiscal_period(instance) -> None:
    validate_date_range(instance.start_date, instance.end_date)
    if instance.fiscal_year_id:
        fy = instance.fiscal_year
        if instance.company_id and fy.company_id != instance.company_id:
            raise ValidationError(_("Fiscal period company does not match its fiscal year."))
        if instance.start_date and instance.start_date < fy.start_date:
            raise ValidationError(_("Fiscal period starts before its fiscal year."))
        if instance.end_date and instance.end_date > fy.end_date:
            raise ValidationError(_("Fiscal period ends after its fiscal year."))
        if (
            instance.start_date
            and instance.end_date
            and fiscal_periods_overlap(
                instance.fiscal_year_id,
                instance.start_date,
                instance.end_date,
                exclude_id=instance.pk,
            )
        ):
            raise ValidationError(_("Fiscal period overlaps another period in this fiscal year."))
