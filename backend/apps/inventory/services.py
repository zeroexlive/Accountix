"""Inventory application services (Sprint 03).

All posting runs inside ``transaction.atomic`` and every validation —
including the full movement plan and any GL posting — is computed before
stock movements are written, so a rejected document persists no movements.

Valuation is Moving Weighted Average Cost per (company, warehouse,
product), derived from the movement ledger itself:

- RECEIPT: valued at the line's unit cost; the new average is
  (old value + receipt value) / (old qty + receipt qty) by construction.
- ISSUE: valued at the current average; issuing the entire remaining
  quantity takes the entire remaining value (no residual cents).
- TRANSFER: out of the source at its average, into the destination at
  exactly that cost — total quantity and value are preserved.
- ADJUSTMENT: positive at the supplied cost (or current average);
  negative at the current average, like an issue.
- Returns are modelled as ordinary RECEIPT/ISSUE documents carrying a
  source reference; there is no special return type in this sprint.
- Movements are applied in posting order. Backdated documents therefore
  value at the average *at posting time*, not at the document date —
  a documented limitation until revaluation rules ship
  (INVENTORY_RULES rule 7).

Accounting integration is explicit opt-in only (ADR-013): the caller may
pass ``gl_accounts=(inventory_account, offset_account)`` for a RECEIPT
(debit inventory / credit offset) or an ISSUE (debit offset / credit
inventory). Nothing is hardcoded and no journal is posted by default.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.inventory import reporting

ZERO = Decimal("0")
CENT = Decimal("0.01")


def _dec(value, field: str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValidationError(f"{field} is not a valid decimal.") from None
    if amount.is_nan() or amount.is_infinite():
        raise ValidationError(f"{field} is not finite.")
    return amount


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Document creation (DRAFT)
# ---------------------------------------------------------------------------


def _validate_header(company, doc_type, warehouse, destination_warehouse):
    from apps.inventory.models import StockDocument

    if doc_type not in StockDocument.DocType.values:
        raise ValidationError(f"Unknown stock document type: {doc_type}.")
    if warehouse.company_id != company.id:
        raise ValidationError("Warehouse belongs to a different company.")
    if not warehouse.is_active:
        raise ValidationError(f"Warehouse {warehouse.code} is inactive.")
    if doc_type == StockDocument.DocType.TRANSFER:
        if destination_warehouse is None:
            raise ValidationError("A transfer needs a destination warehouse.")
        if destination_warehouse.pk == warehouse.pk:
            raise ValidationError("Transfer source and destination must differ.")
        if destination_warehouse.company_id != company.id:
            raise ValidationError("Destination warehouse belongs to a different company.")
        if not destination_warehouse.is_active:
            raise ValidationError(f"Warehouse {destination_warehouse.code} is inactive.")
    elif destination_warehouse is not None:
        raise ValidationError("Only transfers take a destination warehouse.")


def _validate_line(company, doc_type, raw):
    product = raw.get("product")
    if product is None or product.company_id != company.id:
        raise ValidationError("Line product belongs to a different company (or is missing).")
    if not product.is_active:
        raise ValidationError(f"Product {product.sku} is inactive.")
    if not product.is_stockable:
        raise ValidationError(
            f"Product {product.sku} is not stockable; services cannot move through inventory."
        )
    unit = raw.get("unit") or product.base_unit
    if unit.company_id != company.id:
        raise ValidationError("Line unit belongs to a different company.")
    quantity = _dec(raw.get("quantity", ZERO), "quantity")
    if quantity == ZERO:
        raise ValidationError("Line quantity cannot be zero.")
    if doc_type != "ADJUSTMENT" and quantity < ZERO:
        raise ValidationError("Line quantity must be positive for this document type.")
    unit_cost = raw.get("unit_cost")
    if unit_cost is not None:
        unit_cost = _dec(unit_cost, "unit_cost")
        if unit_cost < ZERO:
            raise ValidationError("Unit cost cannot be negative.")
    return product, unit, quantity, unit_cost


@transaction.atomic
def create_stock_document(
    *,
    company,
    doc_type,
    warehouse,
    doc_date,
    lines,
    destination_warehouse=None,
    description="",
    source_type="",
    source_id="",
):
    """Validate and persist a DRAFT stock document with its lines."""
    from apps.inventory.models import StockDocument, StockDocumentLine

    _validate_header(company, doc_type, warehouse, destination_warehouse)
    if not lines:
        raise ValidationError("A stock document needs at least one line.")
    validated = [_validate_line(company, doc_type, raw) for raw in lines]

    doc = StockDocument.objects.create(
        company=company,
        warehouse=warehouse,
        destination_warehouse=destination_warehouse,
        doc_type=doc_type,
        doc_date=doc_date,
        description=description,
        source_type=source_type,
        source_id=source_id,
    )
    for product, unit, quantity, unit_cost in validated:
        StockDocumentLine.objects.create(
            document=doc, product=product, unit=unit, quantity=quantity, unit_cost=unit_cost
        )
    return doc


# ---------------------------------------------------------------------------
# Posting
# ---------------------------------------------------------------------------


def _balance_map(company):
    cache: dict = {}

    def balance(warehouse, product):
        key = (warehouse.pk, product.pk)
        if key not in cache:
            cache[key] = reporting.stock_balance(company, warehouse, product)
        return cache[key]

    def apply(warehouse, product, qty_delta, value_delta):
        current = balance(warehouse, product)
        qty = current["quantity"] + qty_delta
        value = current["value"] + value_delta
        cache[(warehouse.pk, product.pk)] = {
            "quantity": qty,
            "value": value,
            "average_cost": (value / qty) if qty > 0 else ZERO,
        }

    return balance, apply


def _issue_value(balance_row, qty_out: Decimal, sku: str):
    """Value an outflow at the moving average; full outflow takes all value."""
    available = balance_row["quantity"]
    if qty_out > available:
        raise ValidationError(
            f"Insufficient stock for {sku}: requested {qty_out}, available {available}."
        )
    if qty_out == available:
        return balance_row["value"], balance_row["average_cost"]
    avg = balance_row["average_cost"]
    return _money(qty_out * avg), avg


def _plan_movements(company, doc):
    """Return (movement dicts, gl_total). Pure validation — writes nothing."""
    from apps.catalog.services import convert_quantity

    balance, apply = _balance_map(company)
    planned = []
    gl_total = ZERO

    def add(warehouse, line, qty_delta, unit_cost, value_delta):
        planned.append(
            {
                "warehouse": warehouse,
                "line": line,
                "product": line.product,
                "quantity_delta": qty_delta,
                "unit_cost": unit_cost,
                "value_delta": value_delta,
            }
        )
        apply(warehouse, line.product, qty_delta, value_delta)

    for line in doc.lines.select_related("product", "unit", "product__base_unit").all():
        product = line.product
        unit = line.unit or product.base_unit
        base_qty = convert_quantity(
            product=product, quantity=line.quantity, from_unit=unit, to_unit=product.base_unit
        )
        if doc.doc_type == "RECEIPT":
            if line.unit_cost is None:
                raise ValidationError(f"Receipt of {product.sku} needs a unit cost.")
            # unit_cost is priced per line unit; movements store the
            # equivalent cost per base unit.
            value = _money(line.quantity * line.unit_cost)
            add(doc.warehouse, line, base_qty, value / base_qty, value)
            gl_total += value
        elif doc.doc_type == "ISSUE":
            row = balance(doc.warehouse, product)
            value, avg = _issue_value(row, base_qty, product.sku)
            add(doc.warehouse, line, -base_qty, avg, -value)
            gl_total += value
        elif doc.doc_type == "TRANSFER":
            row = balance(doc.warehouse, product)
            value, avg = _issue_value(row, base_qty, product.sku)
            add(doc.warehouse, line, -base_qty, avg, -value)
            add(doc.destination_warehouse, line, base_qty, avg, value)
        elif doc.doc_type == "ADJUSTMENT":
            if base_qty > ZERO:
                row = balance(doc.warehouse, product)
                if line.unit_cost is not None:
                    value = _money(line.quantity * line.unit_cost)
                    add(doc.warehouse, line, base_qty, value / base_qty, value)
                else:
                    if row["quantity"] <= ZERO:
                        raise ValidationError(
                            f"Positive adjustment of {product.sku} with no existing stock "
                            "needs a unit cost."
                        )
                    value = _money(base_qty * row["average_cost"])
                    add(doc.warehouse, line, base_qty, row["average_cost"], value)
            else:
                row = balance(doc.warehouse, product)
                value, avg = _issue_value(row, -base_qty, product.sku)
                add(doc.warehouse, line, base_qty, avg, -value)
        else:  # pragma: no cover - header validation already restricts types
            raise ValidationError(f"Unsupported document type {doc.doc_type}.")
    return planned, gl_total


def _resolve_gl_accounts(company, gl_accounts):
    from apps.accounting.models import Account

    resolved = []
    for item in gl_accounts:
        account = item if isinstance(item, Account) else Account.objects.filter(pk=item).first()
        if account is None:
            raise ValidationError("GL account not found.")
        if account.company_id != company.id:
            raise ValidationError("GL account belongs to a different company.")
        resolved.append(account)
    return resolved


@transaction.atomic
def post_stock_document(document, *, user=None, gl_accounts=None):
    """Post a DRAFT stock document: write its movements atomically."""
    from apps.audit.services import record_event
    from apps.inventory.models import StockDocument, StockMovement

    doc = StockDocument.objects.select_for_update().get(pk=document.pk)
    if doc.status != StockDocument.Status.DRAFT:
        raise ValidationError("Only a DRAFT stock document can be posted.")

    gl_pair = None
    if gl_accounts is not None:
        if doc.doc_type not in ("RECEIPT", "ISSUE"):
            raise ValidationError("GL posting is supported only for RECEIPT and ISSUE documents.")
        if len(gl_accounts) != 2:
            raise ValidationError("gl_accounts must be (inventory_account, offset_account).")
        gl_pair = _resolve_gl_accounts(doc.company, gl_accounts)

    planned, gl_total = _plan_movements(doc.company, doc)

    journal_entry = None
    if gl_pair is not None and gl_total > ZERO:
        from apps.accounting.services import post_journal_entry

        inventory_account, offset_account = gl_pair
        if doc.doc_type == "RECEIPT":
            gl_lines = [
                {"account": inventory_account, "debit": gl_total},
                {"account": offset_account, "credit": gl_total},
            ]
        else:  # ISSUE
            gl_lines = [
                {"account": offset_account, "debit": gl_total},
                {"account": inventory_account, "credit": gl_total},
            ]
        journal_entry = post_journal_entry(
            company=doc.company,
            entry_date=doc.doc_date,
            lines=gl_lines,
            description=f"Stock {doc.doc_type.lower()} {doc.id}",
            user=user,
            source_type="STOCK_DOCUMENT",
            source_id=str(doc.id),
            idempotency_key=f"stock-doc:{doc.id}",
        )

    for item in planned:
        StockMovement.objects.create(
            company=doc.company,
            warehouse=item["warehouse"],
            product=item["product"],
            quantity_delta=item["quantity_delta"],
            unit_cost=item["unit_cost"],
            value_delta=item["value_delta"],
            movement_date=doc.doc_date,
            document=doc,
            document_line=item["line"],
            created_by=user,
        )

    doc.status = StockDocument.Status.POSTED
    doc.posted_by = user
    doc.posted_at = timezone.now()
    doc.journal_entry = journal_entry
    doc.save()
    record_event(
        action="stock.posted",
        entity_type="StockDocument",
        company=doc.company,
        user=user,
        entity_id=doc.id,
        doc_type=doc.doc_type,
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
    )
    return doc


# ---------------------------------------------------------------------------
# Convenience wrappers (single-line documents)
# ---------------------------------------------------------------------------


@transaction.atomic
def receive_stock(
    *,
    company,
    warehouse,
    product,
    quantity,
    unit_cost,
    doc_date,
    user=None,
    unit=None,
    description="",
    source_type="",
    source_id="",
    gl_accounts=None,
):
    doc = create_stock_document(
        doc_type="RECEIPT",
        company=company,
        warehouse=warehouse,
        doc_date=doc_date,
        lines=[{"product": product, "quantity": quantity, "unit_cost": unit_cost, "unit": unit}],
        description=description,
        source_type=source_type,
        source_id=source_id,
    )
    return post_stock_document(doc, user=user, gl_accounts=gl_accounts)


@transaction.atomic
def issue_stock(
    *,
    company,
    warehouse,
    product,
    quantity,
    doc_date,
    user=None,
    unit=None,
    description="",
    source_type="",
    source_id="",
    gl_accounts=None,
):
    doc = create_stock_document(
        doc_type="ISSUE",
        company=company,
        warehouse=warehouse,
        doc_date=doc_date,
        lines=[{"product": product, "quantity": quantity, "unit": unit}],
        description=description,
        source_type=source_type,
        source_id=source_id,
    )
    return post_stock_document(doc, user=user, gl_accounts=gl_accounts)


@transaction.atomic
def transfer_stock(
    *,
    company,
    warehouse,
    destination_warehouse,
    product,
    quantity,
    doc_date,
    user=None,
    unit=None,
    description="",
):
    doc = create_stock_document(
        doc_type="TRANSFER",
        company=company,
        warehouse=warehouse,
        destination_warehouse=destination_warehouse,
        doc_date=doc_date,
        lines=[{"product": product, "quantity": quantity, "unit": unit}],
        description=description,
    )
    return post_stock_document(doc, user=user)


@transaction.atomic
def adjust_stock(
    *,
    company,
    warehouse,
    product,
    quantity_delta,
    doc_date,
    reason="",
    user=None,
    unit=None,
    unit_cost=None,
):
    """Signed adjustment; ``quantity_delta`` may be negative. Reason is kept
    as the document description so the adjustment is always explained."""
    doc = create_stock_document(
        doc_type="ADJUSTMENT",
        company=company,
        warehouse=warehouse,
        doc_date=doc_date,
        lines=[
            {"product": product, "quantity": quantity_delta, "unit": unit, "unit_cost": unit_cost}
        ],
        description=reason,
    )
    return post_stock_document(doc, user=user)


# ---------------------------------------------------------------------------
# Reversal
# ---------------------------------------------------------------------------


@transaction.atomic
def reverse_stock_document(document, *, user=None, reason="", reversal_date=None):
    """Reverse a POSTED document with exact negating movements.

    History is never edited: a new POSTED reversal document carries the
    negating movements, the original flips to REVERSED, and a
    StockDocumentReversal record links them. Reversal is rejected when it
    would drive any balance negative (e.g. the received stock was already
    issued), when the document was already reversed, or when it is itself
    a reversal. A linked GL journal entry is reversed through the
    accounting service in the same transaction.
    """
    from apps.audit.services import record_event
    from apps.inventory.models import (
        StockDocument,
        StockDocumentLine,
        StockDocumentReversal,
        StockMovement,
    )

    doc = StockDocument.objects.select_for_update().get(pk=document.pk)
    if doc.reversal_of_id is not None:
        raise ValidationError("A reversal document cannot itself be reversed.")
    if doc.status == StockDocument.Status.REVERSED:
        raise ValidationError("This document has already been reversed.")
    if doc.status != StockDocument.Status.POSTED:
        raise ValidationError("Only a POSTED stock document can be reversed.")
    if StockDocumentReversal.objects.filter(original_document=doc).exists():
        raise ValidationError("This document has already been reversed.")

    originals = list(doc.movements.all())
    if not originals:
        raise ValidationError("Document has no movements and cannot be reversed.")

    # Guard: negating must not drive any (warehouse, product) balance negative.
    balance, apply = _balance_map(doc.company)
    for movement in originals:
        row = balance(movement.warehouse, movement.product)
        if row["quantity"] - movement.quantity_delta < ZERO:
            raise ValidationError(
                f"Reversal would make stock of {movement.product.sku} negative "
                f"in warehouse {movement.warehouse.code}."
            )
        apply(
            movement.warehouse,
            movement.product,
            -movement.quantity_delta,
            -movement.value_delta,
        )

    rev_date = reversal_date or doc.doc_date
    reversal_doc = StockDocument.objects.create(
        company=doc.company,
        warehouse=doc.warehouse,
        destination_warehouse=doc.destination_warehouse,
        doc_type=doc.doc_type,
        doc_date=rev_date,
        description=f"Reversal of {doc.doc_type} {doc.doc_date}: {reason}".strip(),
        source_type="REVERSAL",
        source_id=str(doc.id),
        reversal_of=doc,
    )
    for line in doc.lines.all():
        StockDocumentLine.objects.create(
            document=reversal_doc,
            product=line.product,
            unit=line.unit,
            quantity=line.quantity,
            unit_cost=line.unit_cost,
        )
    for movement in originals:
        StockMovement.objects.create(
            company=doc.company,
            warehouse=movement.warehouse,
            product=movement.product,
            quantity_delta=-movement.quantity_delta,
            unit_cost=movement.unit_cost,
            value_delta=-movement.value_delta,
            movement_date=rev_date,
            document=reversal_doc,
            document_line=None,
            created_by=user,
        )

    if doc.journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=doc.journal_entry, user=user, reason=reason, reversal_date=rev_date
        )

    reversal_doc.status = StockDocument.Status.POSTED
    reversal_doc.posted_by = user
    reversal_doc.posted_at = timezone.now()
    reversal_doc.save()

    StockDocumentReversal.objects.create(
        original_document=doc, reversal_document=reversal_doc, reversed_by=user, reason=reason
    )

    doc.status = StockDocument.Status.REVERSED
    doc.save()  # model guard permits exactly this transition

    record_event(
        action="stock.reversed",
        entity_type="StockDocument",
        company=doc.company,
        user=user,
        entity_id=doc.id,
        reversal_document_id=str(reversal_doc.id),
        reason=reason,
    )
    return reversal_doc
