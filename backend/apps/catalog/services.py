"""Catalog services: hierarchy/conversion validation and quantity conversion."""

from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

ZERO = Decimal("0")


def _to_decimal(value, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} is not a valid decimal.") from None
    if amount.is_nan() or amount.is_infinite():
        raise ValidationError(f"{field} is not finite.")
    return amount


def validate_category_hierarchy(category) -> None:
    parent = category.parent
    if parent is None:
        return
    if category.pk and parent.pk == category.pk:
        raise ValidationError("A category cannot be its own parent.")
    if parent.company_id != category.company_id:
        raise ValidationError("Parent category belongs to a different company.")
    seen: set = set()
    node = parent
    while node is not None:
        if category.pk and node.pk == category.pk:
            raise ValidationError("Category hierarchy would contain a cycle.")
        if node.pk in seen:
            raise ValidationError("Existing category hierarchy contains a cycle.")
        seen.add(node.pk)
        node = node.parent


def validate_conversion(conversion) -> None:
    if conversion.from_unit_id == conversion.to_unit_id:
        raise ValidationError("Conversion source and target units must differ.")
    if conversion.factor is None or conversion.factor <= ZERO:
        raise ValidationError("Conversion factor must be positive.")
    if conversion.product.company_id != conversion.company_id:
        raise ValidationError("Conversion product belongs to a different company.")
    for unit in (conversion.from_unit, conversion.to_unit):
        if unit.company_id != conversion.company_id:
            raise ValidationError("Conversion unit belongs to a different company.")


def convert_quantity(*, product, quantity, from_unit, to_unit) -> Decimal:
    """Convert ``quantity`` of ``product`` between units of the same company.

    Uses the product's direct conversion (multiply) or its inverse
    (divide). Same unit is the identity. Anything else is rejected rather
    than guessed.
    """
    qty = _to_decimal(quantity, "quantity")
    if from_unit.pk == to_unit.pk:
        return qty
    from apps.catalog.models import ProductUnitConversion

    conv = ProductUnitConversion.objects.filter(
        product=product, from_unit=from_unit, to_unit=to_unit
    ).first()
    if conv is not None:
        return qty * conv.factor
    inverse = ProductUnitConversion.objects.filter(
        product=product, from_unit=to_unit, to_unit=from_unit
    ).first()
    if inverse is not None:
        return qty / inverse.factor
    raise ValidationError(
        f"No unit conversion for product {product.sku} from {from_unit.code} to {to_unit.code}."
    )
