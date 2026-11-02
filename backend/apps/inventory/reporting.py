"""Inventory reporting — derived ONLY from ``StockMovement`` rows.

There is no StockBalance table in Sprint 03 (ADR-012): every figure here
is an aggregation of the append-only ledger, so reported balances
reconcile with the sum of movements by construction (and by test).
"""

from decimal import Decimal

from django.db.models import Sum

from apps.inventory.models import StockMovement

ZERO_QTY = Decimal("0")
ZERO_VAL = Decimal("0.00")


def _movements(company, *, warehouse=None, product=None):
    qs = StockMovement.objects.filter(company=company)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if product is not None:
        qs = qs.filter(product=product)
    return qs


def _summarize(qty, value):
    qty = qty if qty is not None else ZERO_QTY
    value = value if value is not None else ZERO_VAL
    average_cost = (value / qty) if qty > 0 else Decimal("0")
    return {"quantity": qty, "value": value, "average_cost": average_cost}


def stock_balance(company, warehouse, product):
    """Quantity, value and MWAC for one (warehouse, product)."""
    agg = _movements(company, warehouse=warehouse, product=product).aggregate(
        qty=Sum("quantity_delta"), val=Sum("value_delta")
    )
    return _summarize(agg["qty"], agg["val"])


def stock_balances(company, *, warehouse=None):
    """One row per (warehouse, product) that has any movement."""
    grouped = (
        _movements(company, warehouse=warehouse)
        .values(
            "warehouse_id",
            "warehouse__code",
            "product_id",
            "product__sku",
            "product__name",
            "product__min_stock_level",
        )
        .annotate(qty=Sum("quantity_delta"), val=Sum("value_delta"))
        .order_by("warehouse__code", "product__sku")
    )
    rows = []
    for row in grouped:
        summary = _summarize(row["qty"], row["val"])
        rows.append(
            {
                "warehouse_id": row["warehouse_id"],
                "warehouse_code": row["warehouse__code"],
                "product_id": row["product_id"],
                "sku": row["product__sku"],
                "name": row["product__name"],
                "min_stock_level": row["product__min_stock_level"],
                **summary,
            }
        )
    return rows


def inventory_valuation(company, *, warehouse=None):
    """Total stock value (sum of movement values) for a company."""
    agg = _movements(company, warehouse=warehouse).aggregate(val=Sum("value_delta"))
    return agg["val"] if agg["val"] is not None else ZERO_VAL


def movement_history(company, product, *, warehouse=None):
    """Chronological movements for one product."""
    return list(
        _movements(company, warehouse=warehouse, product=product)
        .select_related("warehouse", "document")
        .order_by("movement_date", "created_at")
    )


def low_stock(company):
    """Stockable, active products whose total quantity across all of the
    company's warehouses is below their (positive) minimum stock level.
    Products with no movements at all count as quantity zero."""
    from apps.catalog.models import Product

    totals = {
        row["product_id"]: (row["qty"] if row["qty"] is not None else ZERO_QTY)
        for row in _movements(company).values("product_id").annotate(qty=Sum("quantity_delta"))
    }
    rows = []
    products = Product.objects.filter(
        company=company, is_stockable=True, is_active=True, min_stock_level__gt=0
    ).order_by("sku")
    for product in products:
        qty = totals.get(product.id, ZERO_QTY)
        if qty < product.min_stock_level:
            rows.append(
                {
                    "product_id": product.id,
                    "sku": product.sku,
                    "name": product.name,
                    "quantity": qty,
                    "min_stock_level": product.min_stock_level,
                }
            )
    return rows
