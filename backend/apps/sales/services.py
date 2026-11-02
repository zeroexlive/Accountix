"""Sales application services (Sprint 05).

Every posting runs inside ``transaction.atomic`` and validates before it
writes, so a rejected invoice/return persists nothing — no stock
movements, no journals, no totals snapshot. An insufficient-stock sale is
therefore rejected whole: the invoice stays DRAFT.

Data flow of ``post_sales_invoice``:

1. Totals are computed from the lines with ``Decimal`` exactly as in
   purchasing: per line ``gross = qty * unit_price`` (half-up cents),
   ``net = gross - line discount``, ``tax = net * tax_rate`` (rate is a
   snapshot on the line; no rate is hardcoded). Invoice totals are sums.
2. Stockable lines are issued from the invoice warehouse through the
   inventory services (an ISSUE stock document sourced from this
   invoice) at the current moving weighted average; the issue document's
   movement value is the COGS of the sale.
3. GL is explicit opt-in, mirroring ADR-013: the caller supplies
   ``gl_accounts={"receivables", "revenue", "tax_payable", "cogs",
   "inventory"}`` and **two** journal entries are posted (ADR-020):

   - revenue entry — Dr receivables (grand total, tagged with the
     customer for the subledger, ADR-015), Cr revenue (net total),
     Cr tax payable (tax total); key ``sales-invoice:<id>``;
   - COGS entry — Dr COGS, Cr inventory, both at the issue value;
     key ``sales-invoice-cogs:<id>``.

   Without ``gl_accounts`` the stock still issues and the invoice keeps
   both journal fields NULL — a visible, queryable state, not a silent
   skip. No account code is hardcoded anywhere in this module.

Sales returns restore stock at the **original sale's COGS unit cost**
(ADR-021), read back from the original issue document's movements, so
the COGS reversal is exact even if the moving average has moved since.
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


def validate_quotation_line(line) -> None:
    if line.quotation_id is None:
        return
    _validate_product_line(
        line.quotation.company,
        line.product,
        line.unit,
        line.quantity,
        line.unit_price,
        "unit price",
    )


def validate_invoice_line(line) -> None:
    if line.invoice_id is None:
        return
    _validate_product_line(
        line.invoice.company, line.product, line.unit, line.quantity, line.unit_price, "unit price"
    )
    if line.discount_amount is not None and line.discount_amount < ZERO:
        raise ValidationError("Line discount cannot be negative.")
    if line.discount_amount is not None and line.discount_amount > line.gross_amount():
        raise ValidationError("Line discount cannot exceed the line gross amount.")
    if line.tax_rate is not None and line.tax_rate < ZERO:
        raise ValidationError("Line tax rate cannot be negative.")


def validate_return_line(line) -> None:
    if line.sales_return_id is None or line.invoice_line_id is None:
        return
    ret = line.sales_return
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


def _check_warehouse(company, warehouse):
    if warehouse.company_id != company.id:
        raise ValidationError("Warehouse belongs to a different company.")
    if not warehouse.is_active:
        raise ValidationError(f"Warehouse {warehouse.code} is inactive.")


@transaction.atomic
def create_sales_quotation(
    *, company, customer, quotation_number, quotation_date, lines, valid_until=None, description=""
):
    """Validate and persist a DRAFT sales quotation with its lines."""
    from apps.parties.services import require_customer
    from apps.sales.models import SalesQuotation, SalesQuotationLine

    require_customer(company, customer)
    if not lines:
        raise ValidationError("A sales quotation needs at least one line.")
    quotation = SalesQuotation(
        company=company,
        customer=customer,
        quotation_number=quotation_number,
        quotation_date=quotation_date,
        valid_until=valid_until,
        description=description,
    )
    quotation.full_clean()
    quotation.save()
    for raw in lines:
        line = SalesQuotationLine(
            quotation=quotation,
            product=raw.get("product"),
            unit=raw.get("unit"),
            quantity=_dec(raw.get("quantity", ZERO), "quantity"),
            unit_price=_dec(raw.get("unit_price", ZERO), "unit_price"),
        )
        line.full_clean()
        line.save()
    return quotation


@transaction.atomic
def create_sales_invoice(
    *,
    company,
    customer,
    invoice_number,
    invoice_date,
    warehouse,
    lines,
    quotation=None,
    description="",
):
    """Validate and persist a DRAFT sales invoice with its lines."""
    from apps.parties.services import require_customer
    from apps.sales.models import SalesInvoice, SalesInvoiceLine

    require_customer(company, customer)
    _check_warehouse(company, warehouse)
    if quotation is not None:
        if quotation.company_id != company.id:
            raise ValidationError("Quotation belongs to a different company.")
        if quotation.customer_id != customer.id:
            raise ValidationError("Quotation customer does not match the invoice customer.")
    if not lines:
        raise ValidationError("A sales invoice needs at least one line.")

    invoice = SalesInvoice(
        company=company,
        customer=customer,
        quotation=quotation,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        warehouse=warehouse,
        description=description,
    )
    invoice.full_clean(
        exclude=["stock_document", "journal_entry", "cogs_journal_entry", "posted_by"]
    )
    invoice.save()
    for raw in lines:
        line = SalesInvoiceLine(
            invoice=invoice,
            product=raw.get("product"),
            unit=raw.get("unit"),
            quantity=_dec(raw.get("quantity", ZERO), "quantity"),
            unit_price=_dec(raw.get("unit_price", ZERO), "unit_price"),
            discount_amount=_dec(raw.get("discount_amount", ZERO), "discount_amount"),
            tax_rate=_dec(raw.get("tax_rate", ZERO), "tax_rate"),
        )
        line.full_clean()
        line.save()
    return invoice


@transaction.atomic
def convert_quotation_to_invoice(
    quotation, *, invoice_number, invoice_date, warehouse, description=""
):
    """Copy a DRAFT/SENT quotation's lines into a new DRAFT sales invoice
    and mark the quotation CONVERTED."""
    from apps.sales.models import SalesQuotation

    quotation = SalesQuotation.objects.select_for_update().get(pk=quotation.pk)
    if quotation.status not in (SalesQuotation.Status.DRAFT, SalesQuotation.Status.SENT):
        raise ValidationError("Only a DRAFT or SENT quotation can be converted to an invoice.")
    lines = [
        {
            "product": line.product,
            "unit": line.unit,
            "quantity": line.quantity,
            "unit_price": line.unit_price,
        }
        for line in quotation.lines.select_related("product", "unit").all()
    ]
    if not lines:
        raise ValidationError("A sales quotation needs at least one line.")
    invoice = create_sales_invoice(
        company=quotation.company,
        customer=quotation.customer,
        invoice_number=invoice_number,
        invoice_date=invoice_date,
        warehouse=warehouse,
        lines=lines,
        quotation=quotation,
        description=description,
    )
    quotation.status = SalesQuotation.Status.CONVERTED
    quotation.save(update_fields=["status", "updated_at"])
    return invoice


@transaction.atomic
def create_sales_return(
    *, company, original_invoice, return_number, return_date, lines, description=""
):
    """Validate and persist a DRAFT sales return against a POSTED invoice."""
    from apps.sales.models import SalesReturn, SalesReturnLine

    if original_invoice.company_id != company.id:
        raise ValidationError("Original invoice belongs to a different company.")
    if original_invoice.status != "POSTED":
        raise ValidationError("Returns can only be created against a POSTED sales invoice.")
    if not lines:
        raise ValidationError("A sales return needs at least one line.")

    ret = SalesReturn(
        company=company,
        original_invoice=original_invoice,
        return_number=return_number,
        return_date=return_date,
        description=description,
    )
    ret.full_clean(exclude=["stock_document", "journal_entry", "cogs_journal_entry", "posted_by"])
    ret.save()
    for raw in lines:
        invoice_line = raw.get("invoice_line")
        line = SalesReturnLine(
            sales_return=ret,
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
    (= subtotal - discount_total + tax_total). Pure computation — the
    exact mirror of the purchasing computation.
    """
    rows = []
    subtotal = ZERO
    discount_total = ZERO
    tax_total = ZERO
    for line in invoice.lines.select_related("product", "unit").all():
        gross = _money(line.quantity * line.unit_price)
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
    from apps.sales.models import SalesReturnLine

    qs = SalesReturnLine.objects.filter(invoice_line=invoice_line, sales_return__status="POSTED")
    if exclude_return_id is not None:
        qs = qs.exclude(sales_return_id=exclude_return_id)
    agg = qs.aggregate(total=Sum("quantity"))
    return agg["total"] or ZERO


# ---------------------------------------------------------------------------
# Posting — invoice
# ---------------------------------------------------------------------------


@transaction.atomic
def post_sales_invoice(invoice, *, user=None, gl_accounts=None):
    """Post a DRAFT sales invoice: stock issue + optional GL entries.

    Re-posting an already POSTED invoice is idempotent: the invoice is
    returned unchanged and no stock document or journal is duplicated.
    Insufficient stock rejects the whole posting (inventory service
    raises before writing; this transaction rolls back).
    """
    from apps.audit.services import record_event
    from apps.inventory import services as inventory_services
    from apps.sales.models import SalesInvoice

    invoice = SalesInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == SalesInvoice.Status.POSTED:
        return invoice
    if invoice.status != SalesInvoice.Status.DRAFT:
        raise ValidationError("Only a DRAFT sales invoice can be posted.")

    from apps.parties.services import require_customer

    require_customer(invoice.company, invoice.customer)
    if invoice.warehouse.company_id != invoice.company_id:
        raise ValidationError("Warehouse belongs to a different company.")

    rows, totals = compute_invoice_totals(invoice)
    if not rows:
        raise ValidationError("A sales invoice needs at least one line.")
    net_total = totals["subtotal"] - totals["discount_total"]

    accounts = {}
    if gl_accounts is not None:
        accounts = {
            key: _resolve_account(invoice.company, gl_accounts, key)
            for key in ("receivables", "revenue", "tax_payable", "cogs", "inventory")
        }
        if accounts["receivables"] is None:
            raise ValidationError("gl_accounts must include a 'receivables' account.")
        if net_total > ZERO and accounts["revenue"] is None:
            raise ValidationError("gl_accounts must include a 'revenue' account.")
        if totals["tax_total"] > ZERO and accounts["tax_payable"] is None:
            raise ValidationError(
                "gl_accounts must include a 'tax_payable' account when tax is charged."
            )
        if any(r["line"].product.is_stockable for r in rows) and (
            accounts["cogs"] is None or accounts["inventory"] is None
        ):
            raise ValidationError(
                "gl_accounts must include 'cogs' and 'inventory' accounts for stockable lines."
            )

    # 1) Stock issue for stockable lines, valued at the current MWAC.
    stock_document = None
    cogs_value = ZERO
    stock_rows = [r for r in rows if r["line"].product.is_stockable]
    if stock_rows:
        stock_document = inventory_services.create_stock_document(
            company=invoice.company,
            doc_type="ISSUE",
            warehouse=invoice.warehouse,
            doc_date=invoice.invoice_date,
            lines=[
                {
                    "product": r["line"].product,
                    "unit": r["line"].unit,
                    "quantity": r["line"].quantity,
                }
                for r in stock_rows
            ],
            description=f"Sales invoice {invoice.invoice_number}",
            source_type="SALES_INVOICE",
            source_id=str(invoice.id),
        )
        stock_document = inventory_services.post_stock_document(stock_document, user=user)
        cogs_value = -(
            stock_document.movements.aggregate(total=Sum("value_delta"))["total"] or ZERO
        )

    # 2) Tax snapshots on the lines (invoice still DRAFT — lines mutable).
    for r in rows:
        if r["line"].tax_amount != r["tax"]:
            r["line"].tax_amount = r["tax"]
            r["line"].save(update_fields=["tax_amount", "updated_at"])

    # 3) GL entries (opt-in, ADR-020): revenue entry + COGS entry.
    journal_entry = None
    cogs_journal_entry = None
    if gl_accounts is not None and totals["grand_total"] > ZERO:
        from apps.accounting.services import post_journal_entry

        revenue_lines = [
            {
                "account": accounts["receivables"],
                "debit": totals["grand_total"],
                "party": invoice.customer,
            }
        ]
        if net_total > ZERO:
            revenue_lines.append({"account": accounts["revenue"], "credit": net_total})
        if totals["tax_total"] > ZERO:
            revenue_lines.append(
                {"account": accounts["tax_payable"], "credit": totals["tax_total"]}
            )
        journal_entry = post_journal_entry(
            company=invoice.company,
            entry_date=invoice.invoice_date,
            lines=revenue_lines,
            description=f"Sales invoice {invoice.invoice_number}",
            user=user,
            source_type="SALES_INVOICE",
            source_id=str(invoice.id),
            idempotency_key=f"sales-invoice:{invoice.id}",
        )
        if cogs_value > ZERO:
            cogs_journal_entry = post_journal_entry(
                company=invoice.company,
                entry_date=invoice.invoice_date,
                lines=[
                    {"account": accounts["cogs"], "debit": cogs_value},
                    {"account": accounts["inventory"], "credit": cogs_value},
                ],
                description=f"Sales invoice {invoice.invoice_number} — cost of goods sold",
                user=user,
                source_type="SALES_INVOICE_COGS",
                source_id=str(invoice.id),
                idempotency_key=f"sales-invoice-cogs:{invoice.id}",
            )

    invoice.subtotal = totals["subtotal"]
    invoice.discount_total = totals["discount_total"]
    invoice.tax_total = totals["tax_total"]
    invoice.grand_total = totals["grand_total"]
    invoice.stock_document = stock_document
    invoice.journal_entry = journal_entry
    invoice.cogs_journal_entry = cogs_journal_entry
    invoice.status = SalesInvoice.Status.POSTED
    invoice.posted_by = user
    invoice.posted_at = timezone.now()
    invoice.save()
    record_event(
        action="sales.posted",
        entity_type="SalesInvoice",
        company=invoice.company,
        user=user,
        entity_id=invoice.id,
        grand_total=str(invoice.grand_total),
        cogs_value=str(cogs_value),
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
        cogs_journal_entry_id=str(cogs_journal_entry.id) if cogs_journal_entry else "",
        stock_document_id=str(stock_document.id) if stock_document else "",
    )
    return invoice


@transaction.atomic
def reverse_sales_invoice(invoice, *, user=None, reason=""):
    """Reverse a POSTED invoice: reverse its journals and its stock issue
    in one transaction, then flip the invoice to REVERSED. The stock comes
    back into the warehouse; the subledger nets to zero because journal
    reversals keep the party tag (ADR-015)."""
    from apps.audit.services import record_event
    from apps.sales.models import SalesInvoice

    invoice = SalesInvoice.objects.select_for_update().get(pk=invoice.pk)
    if invoice.status == SalesInvoice.Status.REVERSED:
        raise ValidationError("This sales invoice has already been reversed.")
    if invoice.status != SalesInvoice.Status.POSTED:
        raise ValidationError("Only a POSTED sales invoice can be reversed.")

    if invoice.cogs_journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=invoice.cogs_journal_entry,
            user=user,
            reason=reason,
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
    if invoice.stock_document_id is not None:
        from apps.inventory import services as inventory_services

        inventory_services.reverse_stock_document(
            invoice.stock_document,
            user=user,
            reason=reason or f"Sales invoice {invoice.invoice_number} reversed",
            reversal_date=invoice.invoice_date,
        )

    invoice.status = SalesInvoice.Status.REVERSED
    invoice.save()
    record_event(
        action="sales.reversed",
        entity_type="SalesInvoice",
        company=invoice.company,
        user=user,
        entity_id=invoice.id,
        reason=reason,
    )
    return invoice


# ---------------------------------------------------------------------------
# Posting — return
# ---------------------------------------------------------------------------


def _original_issue_unit_cost(invoice, product):
    """COGS unit cost (per base unit) at which ``product`` left stock in
    the original invoice's issue document — read from its movements
    (ADR-021). Returns None when the product was not issued."""
    from apps.inventory.models import StockMovement

    if invoice.stock_document_id is None:
        return None
    agg = StockMovement.objects.filter(
        document_id=invoice.stock_document_id, product=product
    ).aggregate(qty=Sum("quantity_delta"), val=Sum("value_delta"))
    if not agg["qty"]:
        return None
    return (-agg["val"]) / (-agg["qty"])


@transaction.atomic
def post_sales_return(sales_return, *, user=None, gl_accounts=None):
    """Post a DRAFT sales return: receive the goods back into the original
    warehouse at the original sale's COGS unit cost (ADR-021) and, when
    the original invoice was GL-posted and accounts are supplied again,
    reverse the revenue share and the COGS share:

    - Dr revenue (net share) + Dr tax payable (tax share) /
      Cr receivables (grand share, party-tagged), key ``sales-return:<id>``;
    - Dr inventory / Cr COGS at the restored stock value,
      key ``sales-return-cogs:<id>``.

    Revenue/tax shares are proportional to the returned quantity of each
    original line. Re-posting a POSTED return returns it unchanged.
    """
    from apps.audit.services import record_event
    from apps.catalog.services import convert_quantity
    from apps.inventory import services as inventory_services
    from apps.sales.models import SalesReturn

    ret = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if ret.status == SalesReturn.Status.POSTED:
        return ret
    if ret.status != SalesReturn.Status.DRAFT:
        raise ValidationError("Only a DRAFT sales return can be posted.")

    invoice = ret.original_invoice
    if invoice.status != "POSTED":
        raise ValidationError("The original sales invoice is not POSTED.")

    lines = list(ret.lines.select_related("invoice_line", "product", "unit").all())
    if not lines:
        raise ValidationError("A sales return needs at least one line.")

    net_total = ZERO
    tax_total = ZERO
    stock_lines = []
    for line in lines:
        validate_return_line(line)
        already = returned_quantity(line.invoice_line)
        if already + line.quantity > line.invoice_line.quantity:
            raise ValidationError(
                f"Return quantity for {line.product.sku} exceeds the sold "
                f"quantity minus previous returns ({already} already returned)."
            )
        ratio = line.quantity / line.invoice_line.quantity
        line_net = _money(line.invoice_line.net_amount() * ratio)
        line_tax = _money(line_net * (line.invoice_line.tax_rate or ZERO))
        net_total += line_net
        tax_total += line_tax
        if line.product.is_stockable:
            unit_cost = _original_issue_unit_cost(invoice, line.product)
            if unit_cost is None:
                raise ValidationError(
                    f"No issue movement found for {line.product.sku} on the original invoice."
                )
            unit = line.unit or line.product.base_unit
            base_qty = convert_quantity(
                product=line.product,
                quantity=line.quantity,
                from_unit=unit,
                to_unit=line.product.base_unit,
            )
            # unit_cost is priced per line unit; movements store base units.
            stock_lines.append(
                {
                    "product": line.product,
                    "unit": unit,
                    "quantity": line.quantity,
                    "unit_cost": unit_cost * (base_qty / line.quantity),
                }
            )

    stock_document = None
    cogs_value = ZERO
    if stock_lines:
        stock_document = inventory_services.create_stock_document(
            company=ret.company,
            doc_type="RECEIPT",
            warehouse=invoice.warehouse,
            doc_date=ret.return_date,
            lines=stock_lines,
            description=f"Sales return {ret.return_number}",
            source_type="SALES_RETURN",
            source_id=str(ret.id),
        )
        stock_document = inventory_services.post_stock_document(stock_document, user=user)
        cogs_value = stock_document.movements.aggregate(total=Sum("value_delta"))["total"] or ZERO

    journal_entry = None
    cogs_journal_entry = None
    grand_total = net_total + tax_total
    if invoice.journal_entry_id is not None and gl_accounts is not None and grand_total > ZERO:
        from apps.accounting.services import post_journal_entry

        receivables = _resolve_account(ret.company, gl_accounts, "receivables")
        revenue = _resolve_account(ret.company, gl_accounts, "revenue")
        tax_payable = _resolve_account(ret.company, gl_accounts, "tax_payable")
        if receivables is None or revenue is None:
            raise ValidationError(
                "gl_accounts must include 'receivables' and 'revenue' for a return "
                "against a GL-posted invoice."
            )
        if tax_total > ZERO and tax_payable is None:
            raise ValidationError(
                "gl_accounts must include a 'tax_payable' account when tax is reversed."
            )
        reversal_lines = []
        if net_total > ZERO:
            reversal_lines.append({"account": revenue, "debit": net_total})
        if tax_total > ZERO:
            reversal_lines.append({"account": tax_payable, "debit": tax_total})
        reversal_lines.append(
            {"account": receivables, "credit": grand_total, "party": invoice.customer}
        )
        journal_entry = post_journal_entry(
            company=ret.company,
            entry_date=ret.return_date,
            lines=reversal_lines,
            description=f"Sales return {ret.return_number}",
            user=user,
            source_type="SALES_RETURN",
            source_id=str(ret.id),
            idempotency_key=f"sales-return:{ret.id}",
        )
        if cogs_value > ZERO:
            inventory_account = _resolve_account(ret.company, gl_accounts, "inventory")
            cogs_account = _resolve_account(ret.company, gl_accounts, "cogs")
            if inventory_account is None or cogs_account is None:
                raise ValidationError(
                    "gl_accounts must include 'inventory' and 'cogs' for a return "
                    "against a GL-posted invoice."
                )
            cogs_journal_entry = post_journal_entry(
                company=ret.company,
                entry_date=ret.return_date,
                lines=[
                    {"account": inventory_account, "debit": cogs_value},
                    {"account": cogs_account, "credit": cogs_value},
                ],
                description=f"Sales return {ret.return_number} — cost restored",
                user=user,
                source_type="SALES_RETURN_COGS",
                source_id=str(ret.id),
                idempotency_key=f"sales-return-cogs:{ret.id}",
            )

    ret.net_total = net_total
    ret.tax_total = tax_total
    ret.total_amount = grand_total
    ret.cogs_value = cogs_value
    ret.stock_document = stock_document
    ret.journal_entry = journal_entry
    ret.cogs_journal_entry = cogs_journal_entry
    ret.status = SalesReturn.Status.POSTED
    ret.posted_by = user
    ret.posted_at = timezone.now()
    ret.save()
    record_event(
        action="sales_return.posted",
        entity_type="SalesReturn",
        company=ret.company,
        user=user,
        entity_id=ret.id,
        total_amount=str(grand_total),
        cogs_value=str(cogs_value),
        journal_entry_id=str(journal_entry.id) if journal_entry else "",
    )
    return ret


@transaction.atomic
def reverse_sales_return(sales_return, *, user=None, reason=""):
    """Reverse a POSTED sales return (Sprint 07): reverse its journals
    (revenue share, then COGS share) and its stock receipt — the goods
    leave the warehouse again — in one transaction, then flip the return
    to REVERSED. If the restored goods were already sold onward, the
    stock reversal guard rejects the whole reversal.

    ``returned_quantity`` sums POSTED returns only, so the flip restores
    the line's returnable quantity.
    """
    from apps.audit.services import record_event
    from apps.sales.models import SalesReturn

    ret = SalesReturn.objects.select_for_update().get(pk=sales_return.pk)
    if ret.status == SalesReturn.Status.REVERSED:
        raise ValidationError("This sales return has already been reversed.")
    if ret.status != SalesReturn.Status.POSTED:
        raise ValidationError("Only a POSTED sales return can be reversed.")

    if ret.cogs_journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=ret.cogs_journal_entry,
            user=user,
            reason=reason,
            reversal_date=ret.return_date,
        )
    if ret.journal_entry_id is not None:
        from apps.accounting.services import reverse_journal_entry

        reverse_journal_entry(
            entry=ret.journal_entry,
            user=user,
            reason=reason,
            reversal_date=ret.return_date,
        )
    if ret.stock_document_id is not None:
        from apps.inventory import services as inventory_services

        inventory_services.reverse_stock_document(
            ret.stock_document,
            user=user,
            reason=reason or f"Sales return {ret.return_number} reversed",
            reversal_date=ret.return_date,
        )

    ret.status = SalesReturn.Status.REVERSED
    ret.save()
    record_event(
        action="sales_return.reversed",
        entity_type="SalesReturn",
        company=ret.company,
        user=user,
        entity_id=ret.id,
        reason=reason,
    )
    return ret
