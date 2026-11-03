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
    from apps.inventory.models import StockDocument, StockMovement, Warehouse

    doc = StockDocument.objects.select_for_update().get(pk=document.pk)
    if doc.status != StockDocument.Status.DRAFT:
        raise ValidationError("Only a DRAFT stock document can be posted.")

    # Concurrency (Sprint 10, ADR-037): the movement plan is computed
    # from the derived stock balance, so two documents drawing on the
    # same warehouse must not plan concurrently — otherwise both pass
    # the insufficient-stock check against the same balance and the
    # ledger goes negative (proven by the PostgreSQL concurrency
    # tests). Locking the warehouse row(s) before planning serialises
    # posting per warehouse; rows are taken in pk order so transfers
    # (two warehouses) cannot deadlock. The check-then-act sequence is
    # then safe under READ COMMITTED: a waiter re-reads the balance
    # only after the holder commits.
    warehouse_ids = {doc.warehouse_id}
    if doc.destination_warehouse_id is not None:
        warehouse_ids.add(doc.destination_warehouse_id)
    for warehouse_id in sorted(warehouse_ids, key=str):
        Warehouse.objects.select_for_update().get(pk=warehouse_id)

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
# Inventory counts (Sprint 07)
# ---------------------------------------------------------------------------


@transaction.atomic
def create_inventory_count(*, company, warehouse, count_date, lines, description="", user=None):
    """Create a DRAFT inventory count, snapshotting each product's current
    derived balance as ``system_qty``. ``lines`` are dicts with ``product``,
    ``counted_qty`` and an optional ``unit_cost`` (used only to value a
    positive variance for a product with no existing stock)."""
    from apps.inventory.models import InventoryCount, InventoryCountLine

    if warehouse.company_id != company.id:
        raise ValidationError("Warehouse belongs to a different company.")
    if not warehouse.is_active:
        raise ValidationError(f"Warehouse {warehouse.code} is inactive.")
    if not lines:
        raise ValidationError("An inventory count needs at least one line.")

    count = InventoryCount.objects.create(
        company=company,
        warehouse=warehouse,
        count_date=count_date,
        description=description,
    )
    seen = set()
    for raw in lines:
        product = raw.get("product")
        if product is None or product.company_id != company.id:
            raise ValidationError("Count line product belongs to a different company.")
        if not product.is_active:
            raise ValidationError(f"Product {product.sku} is inactive.")
        if not product.is_stockable:
            raise ValidationError(f"Product {product.sku} is not stockable and cannot be counted.")
        if product.pk in seen:
            raise ValidationError(f"Product {product.sku} appears twice in this count.")
        seen.add(product.pk)
        counted_qty = _dec(raw.get("counted_qty", ZERO), "counted_qty")
        if counted_qty < ZERO:
            raise ValidationError("Counted quantity cannot be negative.")
        unit_cost = raw.get("unit_cost")
        if unit_cost is not None:
            unit_cost = _dec(unit_cost, "unit_cost")
            if unit_cost < ZERO:
                raise ValidationError("Unit cost cannot be negative.")
        snapshot = reporting.stock_balance(company, warehouse, product)["quantity"]
        InventoryCountLine.objects.create(
            count=count,
            product=product,
            system_qty=snapshot,
            counted_qty=counted_qty,
            unit_cost=unit_cost,
        )
    return count


@transaction.atomic
def update_inventory_count_lines(count, *, lines, user=None):
    """Update the counted quantities of a DRAFT count's lines (Sprint 13).

    ``create_inventory_count`` snapshots the system quantities and the
    UI seeds the counted quantities with the snapshot; the physical
    count is then typed in on the count page and saved through here
    before posting. ``lines`` are dicts with ``product`` (a Product or
    an existing line's product id), ``counted_qty`` and an optional
    ``unit_cost``. Only lines already on the count can be updated —
    the product set (and its snapshots) is fixed at creation; a
    product that was missed means a fresh count, because its snapshot
    would otherwise be taken at a different moment than the rest.
    """
    from apps.audit.services import record_event
    from apps.inventory.models import InventoryCount

    count = InventoryCount.objects.select_for_update().get(pk=count.pk)
    if count.status != InventoryCount.Status.DRAFT:
        raise ValidationError("Only a DRAFT inventory count can be edited.")

    existing = {line.product_id: line for line in count.lines.all()}
    seen = set()
    for raw in lines:
        product = raw.get("product")
        product_id = getattr(product, "pk", product)
        line = existing.get(product_id)
        if line is None:
            raise ValidationError("Count line product is not part of this count.")
        if product_id in seen:
            raise ValidationError(f"Product {line.product.sku} appears twice.")
        seen.add(product_id)
        counted_qty = _dec(raw.get("counted_qty", ZERO), "counted_qty")
        if counted_qty < ZERO:
            raise ValidationError("Counted quantity cannot be negative.")
        line.counted_qty = counted_qty
        unit_cost = raw.get("unit_cost")
        if unit_cost is not None:
            unit_cost = _dec(unit_cost, "unit_cost")
            if unit_cost < ZERO:
                raise ValidationError("Unit cost cannot be negative.")
        line.unit_cost = unit_cost
        line.save()
    record_event(
        action="stock_count.lines_updated",
        entity_type="InventoryCount",
        company=count.company,
        user=user,
        entity_id=count.id,
        lines_updated=str(len(seen)),
    )
    return count


def _resolve_count_gl_account(company, gl_accounts, key):
    from apps.accounting.models import Account

    item = gl_accounts.get(key)
    if item is None:
        return None
    account = item if isinstance(item, Account) else Account.objects.filter(pk=item).first()
    if account is None:
        raise ValidationError(f"GL account '{key}' not found.")
    if account.company_id != company.id:
        raise ValidationError(f"GL account '{key}' belongs to a different company.")
    if not account.is_postable or not account.is_active:
        raise ValidationError(f"GL account '{key}' is not postable/active.")
    return account


@transaction.atomic
def post_inventory_count(count, *, user=None, gl_accounts=None):
    """Post a DRAFT count: one ADJUSTMENT stock document for all non-zero
    variances, plus an optional GL entry for the net variance value
    (``gl_accounts={"inventory": ..., "variance": ...}``; a net gain is
    Dr inventory / Cr variance, a net loss the mirror; key
    ``stock-count:<id>``).

    The warehouse is assumed frozen since the count was created: if any
    product's current balance no longer equals the snapshot, posting is
    rejected and the count must be recreated — guessing which movements
    belong to the count window would corrupt the ledger.
    """
    from django.db.models import Sum

    from apps.audit.services import record_event
    from apps.inventory.models import InventoryCount

    count = InventoryCount.objects.select_for_update().get(pk=count.pk)
    if count.status == InventoryCount.Status.POSTED:
        return count
    if count.status != InventoryCount.Status.DRAFT:
        raise ValidationError("Only a DRAFT inventory count can be posted.")

    lines = list(count.lines.select_related("product").all())
    if not lines:
        raise ValidationError("An inventory count needs at least one line.")
    for line in lines:
        current = reporting.stock_balance(count.company, count.warehouse, line.product)["quantity"]
        if current != line.system_qty:
            raise ValidationError(
                f"Stock of {line.product.sku} moved since the count was taken "
                f"(snapshot {line.system_qty}, now {current}); recreate the count."
            )

    inventory_account = variance_account = None
    if gl_accounts is not None:
        inventory_account = _resolve_count_gl_account(count.company, gl_accounts, "inventory")
        variance_account = _resolve_count_gl_account(count.company, gl_accounts, "variance")
        if inventory_account is None or variance_account is None:
            raise ValidationError("gl_accounts must include 'inventory' and 'variance' accounts.")

    stock_document = None
    net_value = ZERO
    variance_lines = [line for line in lines if line.variance != ZERO]
    if variance_lines:
        stock_document = create_stock_document(
            company=count.company,
            doc_type="ADJUSTMENT",
            warehouse=count.warehouse,
            doc_date=count.count_date,
            lines=[
                {
                    "product": line.product,
                    "quantity": line.variance,
                    "unit_cost": line.unit_cost,
                }
                for line in variance_lines
            ],
            description=f"Inventory count {count.count_date} variances",
            source_type="INVENTORY_COUNT",
            source_id=str(count.id),
        )
        stock_document = post_stock_document(stock_document, user=user)
        net_value = stock_document.movements.aggregate(total=Sum("value_delta"))["total"] or ZERO

    journal_entry = None
    if gl_accounts is not None and net_value != ZERO:
        from apps.accounting.services import post_journal_entry

        if net_value > ZERO:
            gl_lines = [
                {"account": inventory_account, "debit": net_value},
                {"account": variance_account, "credit": net_value},
            ]
        else:
            gl_lines = [
                {"account": variance_account, "debit": -net_value},
                {"account": inventory_account, "credit": -net_value},
            ]
        journal_entry = post_journal_entry(
            company=count.company,
            entry_date=count.count_date,
            lines=gl_lines,
            description=f"Inventory count {count.count_date} variance",
            user=user,
            source_type="INVENTORY_COUNT",
            source_id=str(count.id),
            idempotency_key=f"stock-count:{count.id}",
        )

    count.stock_document = stock_document
    count.journal_entry = journal_entry
    count.status = InventoryCount.Status.POSTED
    count.posted_by = user
    count.posted_at = timezone.now()
    count.save()
    record_event(
        action="stock_count.posted",
        entity_type="InventoryCount",
        company=count.company,
        user=user,
        entity_id=count.id,
        net_variance_value=str(net_value),
        stock_document_id=str(stock_document.id) if stock_document else "",
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
    )
    return count


@transaction.atomic
def reverse_inventory_count(count, *, user=None, reason=""):
    """Reverse a POSTED count: reverse its GL entry and its adjustment
    document (exact negating movements), create a POSTED reversal count
    with swapped system/counted quantities, and flip the original to
    REVERSED. If the counted stock has since been consumed, the stock
    reversal guard rejects the whole reversal."""
    from apps.audit.services import record_event
    from apps.inventory.models import InventoryCount, InventoryCountLine

    count = InventoryCount.objects.select_for_update().get(pk=count.pk)
    if count.reversal_of_id is not None:
        raise ValidationError("A reversal count cannot itself be reversed.")
    if count.status == InventoryCount.Status.REVERSED:
        raise ValidationError("This inventory count has already been reversed.")
    if count.status != InventoryCount.Status.POSTED:
        raise ValidationError("Only a POSTED inventory count can be reversed.")

    if count.journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=count.journal_entry,
            user=user,
            reason=reason,
            reversal_date=count.count_date,
        )
    reversal_doc = None
    if count.stock_document_id is not None:
        reversal_doc = reverse_stock_document(
            count.stock_document,
            user=user,
            reason=reason or "Inventory count reversed",
            reversal_date=count.count_date,
        )

    reversal_count = InventoryCount.objects.create(
        company=count.company,
        warehouse=count.warehouse,
        count_date=count.count_date,
        description=f"Reversal of count {count.count_date}: {reason}".strip(),
        stock_document=reversal_doc,
        reversal_of=count,
    )
    for line in count.lines.all():
        InventoryCountLine.objects.create(
            count=reversal_count,
            product=line.product,
            system_qty=line.counted_qty,
            counted_qty=line.system_qty,
            unit_cost=line.unit_cost,
        )
    reversal_count.status = InventoryCount.Status.POSTED
    reversal_count.posted_by = user
    reversal_count.posted_at = timezone.now()
    reversal_count.save()

    count.status = InventoryCount.Status.REVERSED
    count.save()  # model guard permits exactly this transition
    record_event(
        action="stock_count.reversed",
        entity_type="InventoryCount",
        company=count.company,
        user=user,
        entity_id=count.id,
        reversal_count_id=str(reversal_count.id),
        reason=reason,
    )
    return reversal_count


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
