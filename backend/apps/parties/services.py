"""Parties services: validation that spans records lives here (ADR-002)."""

from django.core.exceptions import ValidationError


def validate_party(party) -> None:
    from apps.parties.models import Party

    if party.kind not in Party.Kind.values:
        raise ValidationError(f"Unknown party kind: {party.kind}.")
    if not (party.code or "").strip():
        raise ValidationError("Party code cannot be blank.")
    if not (party.name or "").strip():
        raise ValidationError("Party name cannot be blank.")


def require_supplier(company, party) -> None:
    """Guard used by purchasing flows: the party must be an active supplier
    of exactly this company. Cross-company parties are rejected here rather
    than trusted from client input (master prompt §11)."""
    if party is None or party.company_id != company.id:
        raise ValidationError("Supplier belongs to a different company (or is missing).")
    if not party.is_active:
        raise ValidationError(f"Supplier {party.code} is inactive.")
    if not party.is_supplier:
        raise ValidationError(f"Party {party.code} is not a supplier.")


def require_customer(company, party) -> None:
    """Guard used by sales flows: the party must be an active customer of
    exactly this company (mirror of :func:`require_supplier`)."""
    if party is None or party.company_id != company.id:
        raise ValidationError("Customer belongs to a different company (or is missing).")
    if not party.is_active:
        raise ValidationError(f"Customer {party.code} is inactive.")
    if not party.is_customer:
        raise ValidationError(f"Party {party.code} is not a customer.")
