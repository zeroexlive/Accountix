"""Parties services: validation that spans records lives here (ADR-002)."""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


def validate_party(party) -> None:
    from apps.parties.models import Party

    if party.kind not in Party.Kind.values:
        raise ValidationError(_("Unknown party kind: %(kind)s.") % {"kind": party.kind})
    if not (party.code or "").strip():
        raise ValidationError(_("Party code cannot be blank."))
    if not (party.name or "").strip():
        raise ValidationError(_("Party name cannot be blank."))


def require_supplier(company, party) -> None:
    """Guard used by purchasing flows: the party must be an active supplier
    of exactly this company. Cross-company parties are rejected here rather
    than trusted from client input (master prompt §11)."""
    if party is None or party.company_id != company.id:
        raise ValidationError(_("Supplier belongs to a different company (or is missing)."))
    if not party.is_active:
        raise ValidationError(_("Supplier %(code)s is inactive.") % {"code": party.code})
    if not party.is_supplier:
        raise ValidationError(_("Party %(code)s is not a supplier.") % {"code": party.code})


def require_customer(company, party) -> None:
    """Guard used by sales flows: the party must be an active customer of
    exactly this company (mirror of :func:`require_supplier`)."""
    if party is None or party.company_id != company.id:
        raise ValidationError(_("Customer belongs to a different company (or is missing)."))
    if not party.is_active:
        raise ValidationError(_("Customer %(code)s is inactive.") % {"code": party.code})
    if not party.is_customer:
        raise ValidationError(_("Party %(code)s is not a customer.") % {"code": party.code})
