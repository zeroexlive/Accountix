"""Purchasing application services (Sprint 04).

Every posting runs inside ``transaction.atomic`` and validates before it
writes, so a rejected invoice/return persists nothing — no stock
movements, no journal, no totals snapshot.

Data flow of ``post_purchase_invoice``:

1. Totals are computed from the lines with ``Decimal``: per line
   ``gross = qty * unit_cost`` (rounded half-up to cents),
   ``net = gross - line discount``, ``tax = net * tax_rate`` (rate is a
   snapshot on the line; no rate is hardcoded anywhere). Invoice totals
   are the sums and are stored as a snapshot on the posted invoice.
2. Stockable lines are received into the invoice warehouse through the
   inventory services (a RECEIPT stock document sourced from this
   invoice) at their **net** unit cost, so the stock ledger value equals
   the accounting inventory debit. Service (non-stockable) lines create
   no movement.
3. GL is explicit opt-in, mirroring ADR-013: the caller supplies the
   accounts as ``gl_accounts={"inventory": ..., "payables": ...,
   "tax": ..., "expense": ...}``. The entry — Dr inventory (actual stock
   value), Dr expense (net service lines), Dr tax (tax total),
   Cr payables (grand total, tagged with the supplier for the subledger,
   ADR-015) — is posted through ``accounting.services.post_journal_entry``
   with idempotency key ``purchase-invoice:<invoice id>``. Without
   ``gl_accounts`` the stock still posts and the invoice keeps
   ``journal_entry = NULL`` — a visible, queryable state, not a silent
   skip. No account code is hardcoded anywhere in this module.

Reversal reuses the inventory and accounting reversal services in the
same transaction; the inventory guard (stock already issued) therefore
blocks invoice reversal exactly as it blocks document reversal.

Additional purchase costs (freight etc.): **deferred** (ADR-017). They
are not allocated into stock value in this sprint; an additional-cost
allocation that is not fully tested would corrupt MWAC.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

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
# Model-level validation (invoked from clean())
# ---------------------------------------------------------------------------


def _validate_product_line(company, product, unit, quantity, unit_price, price_field):
    if product is None or product.company_id != company.id:
        raise ValidationError("Line product belongs to a different company (or is missing).")
    if not product.is_active:
        raise ValidationError(f"Product {product.sku} is inactive.")
    if unit is not None and unit.company_id != company.id:
        raise ValidationError("Line unit belongs to a different company.")
    if quantity is None or quantity <= ZERO:
        raise ValidationError("Line quantity must be positive.")
    if unit_price is None or unit_price < ZERO:
        raise ValidationError(f"Line {price_field} cannot be negative.")


def validate_order_line(line) -> None:
    if line.order_id is None:
        return
    _validate_product_line(
        line.order.company, line.product, line.unit, line.quantity, line.unit_price, "unit price"
    )


def validate_invoice_line(line) -> None:
    if line.invoice_id is None:
        return
    _validate_product_line(
        line.invoice.company, line.product, line.unit, line.quantity, line.unit_cost, "unit cost"
    )
    if line.discount_amount is not None and line.discount_amount < ZERO:
        raise ValidationError("Line discount cannot be negative.")
    if line.discount_amount is not None and line.discount_amount > line.gross_amount():
        raise ValidationError("Line discount cannot exceed the line gross amount.")
    if line.tax_rate is not None and line.tax_rate < ZERO:
        raise ValidationError("Line tax rate cannot be negative.")


def validate_return_line(line) -> None:
    if line.purchase_return_id is None or line.invoice_line_id is None:
        return
    ret = line.purchase_return
    if line.invoice_line.invoice_id != ret.original_invoice_id:
        raise ValidationError("Return line references a line of a different invoice.")
    if line.product_id != line.invoice_line.product_id:
        raise ValidationError("Return line product does not match the invoice line product.")
    if line.quantity is None or line.quantity <= ZERO:
        raise ValidationError("Return line quantity must be positive.")


# ---------------------------------------------------------------------------
# Draft creation
# ---------------------------------------------------------------------------


def _resolve_account(company, gl_accounts, key):
    from apps.accounting.models import Account

    item = gl_accounts.get(key)
    if item is None:
        return None
    account = item if isinstance(item, Account) else Account.objects.filter(pk=item).first()
    if account is None:
        raise ValidationError(f"GL account '{key}' not found.")
    if account.company_id != company.id:
        raise ValidationError(f"GL account '{key}' belongs to a different company.")
    return account


@transaction.atomic
def create_purchase_invoice(
    *,
    company,
    supplier,
    invoice_number,
    invoice_date,
    warehouse,
    lines,
    purchase_order=None,
    description="",
):
    """Validate and persist a DRAFT purchase invoice with its lines."""
    from apps.parties.services import require_supplier
    from apps.purchases.models import PurchaseInvoice, PurchaseInvoiceLine

    require_supplier(company, supplier)
    if warehouse.company_id != company.id:
        raise ValidationError("Warehouse belongs to a different company.")
    if not warehouse.is_active:
        raise ValidationError(f"Warehouse {warehouse.code} is inactive.")
    if purchase_order is not None:
        if purchase_order.company_id != company.id:
            raise ValidationError("Purchase order belongs to a different company.")
        if purchase_order.supplier_id != supplier.id:
            raise ValidationError("Purchase order supplier does not match the invoice supplier.")
    if not lines:
        raise ValidationError("A purchase invoice needs at least one line.")

    invoice = PurchaseInvoice(
        company=company,
        supplier=supplier,
        purchase_order=purchase_order,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        warehouse=warehouse,
        description=description,
    )
    invoice.full_clean(exclude=["stock_document", "journal_entry", "posted_by"])
    invoice.save()
    for raw in lines:
        line = PurchaseInvoiceLine(
            invoice=invoice,
            product=raw.get("product"),
            unit=raw.get("unit"),
            quantity=_dec(raw.get("quantity", ZERO), "quantity"),
            unit_cost=_dec(raw.get("unit_cost", ZERO), "unit_cost"),
            discount_amount=_dec(raw.get("discount_amount", ZERO), "discount_amount"),
            tax_rate=_dec(raw.get("tax_rate", ZERO), "tax_rate"),
        )
        line.full_clean()
        line.save()
    return invoice


@transaction.atomic
def create_purchase_return(
    *, company, original_invoice, return_number, return_date, lines, description=""
):
    """Validate and persist a DRAFT purchase return against a POSTED invoice."""
    from apps.purchases.models import PurchaseReturn, PurchaseReturnLine

    if original_invoice.company_id != company.id:
        raise ValidationError("Original invoice belongs to a different company.")
    if original_invoice.status != "POSTED":
        raise ValidationError("Returns can only be created against a POSTED purchase invoice.")
    if not lines:
        raise ValidationError("A purchase return needs at least one line.")

    ret = PurchaseReturn(
        company=company,
        original_invoice=original_invoice,
        return_number=return_number,
        return_date=return_date,
        description=description,
    )
    ret.full_clean(exclude=["stock_document", "journal_entry", "posted_by"])
    ret.save()
    for raw in lines:
        invoice_line = raw.get("invoice_line")
        line = PurchaseReturnLine(
            purchase_return=ret,
            invoice_line=invoice_line,
            product=raw.get("product") or (invoice_line.product if invoice_line else None),
            unit=raw.get("unit"),
            quantity=_dec(raw.get("quantity", ZERO), "quantity"),
        )
        line.full_clean()
        line.save()
    return ret


# ---------------------------------------------------------------------------
# Totals
# ---------------------------------------------------------------------------


def compute_invoice_totals(invoice):
    """Return (line_rows, totals) computed from the invoice lines.

    line_rows: [{line, gross, discount, net, tax}]; totals has subtotal
    (sum of gross), discount_total, tax_total and grand_total
    (= subtotal - discount_total + tax_total). Pure computation.
    """
    rows = []
    subtotal = ZERO
    discount_total = ZERO
    tax_total = ZERO
    for line in invoice.lines.select_related("product", "unit").all():
        gross = _money(line.quantity * line.unit_cost)
        discount = line.discount_amount or ZERO
        net = gross - discount
        tax = _money(net * (line.tax_rate or ZERO))
        rows.append({"line": line, "gross": gross, "discount": discount, "net": net, "tax": tax})
        subtotal += gross
        discount_total += discount
        tax_total += tax
    totals = {
        "subtotal": subtotal,
        "discount_total": discount_total,
        "tax_total": tax_total,
        "grand_total": subtotal - discount_total + tax_total,
    }
    return rows, totals


def returned_quantity(invoice_line, *, exclude_return_id=None):
    """Quantity of one invoice line already returned by POSTED returns."""
    from apps.purchases.models import PurchaseReturnLine

    qs = PurchaseReturnLine.objects.filter(
        invoice_line=invoice_line, purchase_return__status="POSTED"
    )
    if exclude_return_id is not None:
        qs = qs.exclude(purchase_return_id=exclude_return_id)
    agg = qs.aggregate(total=Sum("quantity"))
    return agg["total"] or ZERO


# ---------------------------------------------------------------------------
# Posting — invoice
# ---------------------------------------------------------------------------


@transaction.atomic
def post_purchase_invoice(invoice, *, user=None, gl_accounts=None):
    """Post a DRAFT purchase invoice: stock receipt + optional GL entry.

    Re-posting an already POSTED invoice is idempotent: the invoice is
    returned unchanged and no stock document or journal is duplicated.
    """
    from apps.audit.services import record_event
    from apps.inventory import services as inventory_services
    from apps.purchases.models import PurchaseInvoice

    invoice = PurchaseInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == PurchaseInvoice.Status.POSTED:
        return invoice
    if invoice.status != PurchaseInvoice.Status.DRAFT:
        raise ValidationError("Only a DRAFT purchase invoice can be posted.")

    from apps.parties.services import require_supplier

    require_supplier(invoice.company, invoice.supplier)
    if invoice.warehouse.company_id != invoice.company_id:
        raise ValidationError("Warehouse belongs to a different company.")

    rows, totals = compute_invoice_totals(invoice)
    if not rows:
        raise ValidationError("A purchase invoice needs at least one line.")

    accounts = {}
    if gl_accounts is not None:
        accounts = {
            key: _resolve_account(invoice.company, gl_accounts, key)
            for key in ("inventory", "payables", "tax", "expense")
        }
        if accounts["payables"] is None:
            raise ValidationError("gl_accounts must include a 'payables' account.")
        stock_net = sum((r["net"] for r in rows if r["line"].product.is_stockable), ZERO)
        service_net = sum((r["net"] for r in rows if not r["line"].product.is_stockable), ZERO)
        if stock_net > ZERO and accounts["inventory"] is None:
            raise ValidationError("gl_accounts must include an 'inventory' account.")
        if service_net > ZERO and accounts["expense"] is None:
            raise ValidationError("gl_accounts must include an 'expense' account.")
        if totals["tax_total"] > ZERO and accounts["tax"] is None:
            raise ValidationError("gl_accounts must include a 'tax' account when tax is charged.")

    # 1) Stock receipt for stockable lines, valued at net unit cost.
    stock_document = None
    inventory_value = ZERO
    stock_rows = [r for r in rows if r["line"].product.is_stockable]
    if stock_rows:
        stock_lines = []
        for r in stock_rows:
            line = r["line"]
            net_unit_cost = r["net"] / line.quantity if line.quantity else ZERO
            stock_lines.append(
                {
                    "product": line.product,
                    "unit": line.unit,
                    "quantity": line.quantity,
                    "unit_cost": net_unit_cost,
                }
            )
        stock_document = inventory_services.create_stock_document(
            company=invoice.company,
            doc_type="RECEIPT",
            warehouse=invoice.warehouse,
            doc_date=invoice.invoice_date,
            lines=stock_lines,
            description=f"Purchase invoice {invoice.invoice_number}",
            source_type="PURCHASE_INVOICE",
            source_id=str(invoice.id),
        )
        stock_document = inventory_services.post_stock_document(stock_document, user=user)
        inventory_value = (
            stock_document.movements.aggregate(total=Sum("value_delta"))["total"] or ZERO
        )

    # 2) Tax snapshots on the lines (invoice still DRAFT — lines mutable).
    for r in rows:
        if r["line"].tax_amount != r["tax"]:
            r["line"].tax_amount = r["tax"]
            r["line"].save(update_fields=["tax_amount", "updated_at"])

    # 3) GL entry (opt-in). Dr inventory/expense/tax, Cr payables (party-tagged).
    journal_entry = None
    if gl_accounts is not None and totals["grand_total"] > ZERO:
        from apps.accounting.services import post_journal_entry

        expense_total = sum((r["net"] for r in rows if not r["line"].product.is_stockable), ZERO)
        journal_lines = []
        if inventory_value > ZERO:
            journal_lines.append({"account": accounts["inventory"], "debit": inventory_value})
        if expense_total > ZERO:
            journal_lines.append({"account": accounts["expense"], "debit": expense_total})
        if totals["tax_total"] > ZERO:
            journal_lines.append({"account": accounts["tax"], "debit": totals["tax_total"]})
        journal_lines.append(
            {
                "account": accounts["payables"],
                "credit": totals["grand_total"],
                "party": invoice.supplier,
            }
        )
        journal_entry = post_journal_entry(
            company=invoice.company,
            entry_date=invoice.invoice_date,
            lines=journal_lines,
            description=f"Purchase invoice {invoice.invoice_number}",
            user=user,
            source_type="PURCHASE_INVOICE",
            source_id=str(invoice.id),
            idempotency_key=f"purchase-invoice:{invoice.id}",
        )

    invoice.subtotal = totals["subtotal"]
    invoice.discount_total = totals["discount_total"]
    invoice.tax_total = totals["tax_total"]
    invoice.grand_total = totals["grand_total"]
    invoice.stock_document = stock_document
    invoice.journal_entry = journal_entry
    invoice.status = PurchaseInvoice.Status.POSTED
    invoice.posted_by = user
    invoice.posted_at = timezone.now()
    invoice.save()
    record_event(
        action="purchase.posted",
        entity_type="PurchaseInvoice",
        company=invoice.company,
        user=user,
        entity_id=invoice.id,
        grand_total=str(invoice.grand_total),
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
        stock_document_id=str(stock_document.id) if stock_document else "",
    )
    return invoice


@transaction.atomic
def reverse_purchase_invoice(invoice, *, user=None, reason=""):
    """Reverse a POSTED invoice: reverse its stock receipt and its journal
    in one transaction, then flip the invoice to REVERSED. The inventory
    guard blocks this when the purchased stock was already issued."""
    from apps.audit.services import record_event
    from apps.purchases.models import PurchaseInvoice

    invoice = PurchaseInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == PurchaseInvoice.Status.REVERSED:
        raise ValidationError("This purchase invoice has already been reversed.")
    if invoice.status != PurchaseInvoice.Status.POSTED:
        raise ValidationError("Only a POSTED purchase invoice can be reversed.")

    if invoice.stock_document_id is not None:
        from apps.inventory import services as inventory_services

        inventory_services.reverse_stock_document(
            invoice.stock_document,
            user=user,
            reason=reason or f"Purchase invoice {invoice.invoice_number} reversed",
            reversal_date=invoice.invoice_date,
        )
    if invoice.journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=invoice.journal_entry,
            user=user,
            reason=reason,
            reversal_date=invoice.invoice_date,
        )

    invoice.status = PurchaseInvoice.Status.REVERSED
    invoice.save()
    record_event(
        action="purchase.reversed",
        entity_type="PurchaseInvoice",
        company=invoice.company,
        user=user,
        entity_id=invoice.id,
        reason=reason,
    )
    return invoice


# ---------------------------------------------------------------------------
# Posting — return
# ---------------------------------------------------------------------------


@transaction.atomic
def post_purchase_return(purchase_return, *, user=None, gl_accounts=None):
    """Post a DRAFT purchase return: issue the goods back to the supplier
    at the current moving average and, when the original invoice was
    GL-posted and accounts are supplied again, Dr payables / Cr inventory
    for the same value (idempotency key ``purchase-return:<id>``).

    The return's ``total_amount`` is the inventory value relieved. Any
    difference against the original purchase price is *not* booked in
    this sprint (no price-variance mapping exists yet — ADR-018).
    Re-posting a POSTED return returns it unchanged.
    """
    from apps.audit.services import record_event
    from apps.inventory import services as inventory_services
    from apps.purchases.models import PurchaseReturn

    ret = PurchaseReturn.objects.select_for_update().get(pk=purchase_return.pk)
    if ret.status == PurchaseReturn.Status.POSTED:
        return ret
    if ret.status != PurchaseReturn.Status.DRAFT:
        raise ValidationError("Only a DRAFT purchase return can be posted.")

    invoice = ret.original_invoice
    if invoice.status != "POSTED":
        raise ValidationError("The original purchase invoice is not POSTED.")

    lines = list(ret.lines.select_related("invoice_line", "product", "unit").all())
    if not lines:
        raise ValidationError("A purchase return needs at least one line.")
    for line in lines:
        validate_return_line(line)
        already = returned_quantity(line.invoice_line)
        if already + line.quantity > line.invoice_line.quantity:
            raise ValidationError(
                f"Return quantity for {line.product.sku} exceeds the purchased "
                f"quantity minus previous returns ({already} already returned)."
            )

    stock_document = inventory_services.create_stock_document(
        company=ret.company,
        doc_type="ISSUE",
        warehouse=invoice.warehouse,
        doc_date=ret.return_date,
        lines=[
            {"product": line.product, "unit": line.unit, "quantity": line.quantity}
            for line in lines
        ],
        description=f"Purchase return {ret.return_number}",
        source_type="PURCHASE_RETURN",
        source_id=str(ret.id),
    )
    stock_document = inventory_services.post_stock_document(stock_document, user=user)
    total = -(stock_document.movements.aggregate(total=Sum("value_delta"))["total"] or ZERO)

    journal_entry = None
    if invoice.journal_entry_id is not None and gl_accounts is not None and total > ZERO:
        from apps.accounting.services import post_journal_entry

        inventory_account = _resolve_account(ret.company, gl_accounts, "inventory")
        payables_account = _resolve_account(ret.company, gl_accounts, "payables")
        if inventory_account is None or payables_account is None:
            raise ValidationError(
                "gl_accounts must include 'inventory' and 'payables' for a return "
                "against a GL-posted invoice."
            )
        journal_entry = post_journal_entry(
            company=ret.company,
            entry_date=ret.return_date,
            lines=[
                {"account": payables_account, "debit": total, "party": invoice.supplier},
                {"account": inventory_account, "credit": total},
            ],
            description=f"Purchase return {ret.return_number}",
            user=user,
            source_type="PURCHASE_RETURN",
            source_id=str(ret.id),
            idempotency_key=f"purchase-return:{ret.id}",
        )

    ret.total_amount = total
    ret.stock_document = stock_document
    ret.journal_entry = journal_entry
    ret.status = PurchaseReturn.Status.POSTED
    ret.posted_by = user
    ret.posted_at = timezone.now()
    ret.save()
    record_event(
        action="purchase_return.posted",
        entity_type="PurchaseReturn",
        company=ret.company,
        user=user,
        entity_id=ret.id,
        total_amount=str(total),
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
    )
    return ret
