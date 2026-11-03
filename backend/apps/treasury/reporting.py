"""Treasury reporting - everything derived, nothing stored.

Balances come from journal lines on the GL accounts (the same
derivation discipline as ADR-010/012/015); open items come from invoice
grand totals minus ACTIVE allocations.
"""

from decimal import Decimal

from django.utils.translation import gettext_lazy as _

from apps.accounting import reporting as accounting_reporting

ZERO = Decimal("0")


def treasury_account_balance(company, treasury_account) -> Decimal:
    """Debit-minus-credit balance of the treasury account's GL account."""
    return accounting_reporting.account_balance(company, treasury_account.gl_account)


def outstanding_cheques(company, *, direction=None):
    from apps.treasury.models import Cheque

    qs = Cheque.objects.filter(
        company=company,
        status__in=(Cheque.Status.RECEIVED, Cheque.Status.DEPOSITED, Cheque.Status.DELIVERED),
    ).order_by("due_date")
    if direction is not None:
        qs = qs.filter(direction=direction)
    return qs


def allocated_amount(invoice) -> Decimal:
    from apps.treasury.services import allocated_total_for_invoice

    return allocated_total_for_invoice(invoice)


def invoice_outstanding(invoice) -> Decimal:
    if invoice.status != "POSTED":
        return ZERO
    return invoice.grand_total - allocated_amount(invoice)


def _allocated_totals(field, invoices):
    """ACTIVE allocated totals for many invoices in ONE grouped query.

    Returns {invoice_id: Decimal}. Sprint 10 performance fix: the
    original open_items called the per-invoice aggregate twice per
    invoice (2N queries — the dashboard needed 116 queries at 50
    invoices); this keeps the count constant as invoices grow.
    """
    from django.db.models import Sum

    from apps.treasury.models import PaymentAllocation

    ids = [invoice.id for invoice in invoices]
    if not ids:
        return {}
    rows = (
        PaymentAllocation.objects.filter(
            status=PaymentAllocation.Status.ACTIVE, **{f"{field}__in": ids}
        )
        .values(field)
        .annotate(total=Sum("amount"))
    )
    return {row[field]: row["total"] or ZERO for row in rows}


def open_items(company, *, party=None):
    """Per-invoice open items for POSTED sales and purchase invoices
    with a positive outstanding amount."""
    from apps.purchases.models import PurchaseInvoice
    from apps.sales.models import SalesInvoice

    items = []
    sales_qs = SalesInvoice.objects.filter(company=company, status="POSTED")
    purchase_qs = PurchaseInvoice.objects.filter(company=company, status="POSTED")
    if party is not None:
        sales_qs = sales_qs.filter(customer=party)
        purchase_qs = purchase_qs.filter(supplier=party)
    sales_invoices = list(sales_qs.select_related("customer"))
    purchase_invoices = list(purchase_qs.select_related("supplier"))
    sales_allocated = _allocated_totals("sales_invoice", sales_invoices)
    purchase_allocated = _allocated_totals("purchase_invoice", purchase_invoices)
    for invoice in sales_invoices:
        allocated = sales_allocated.get(invoice.id, ZERO)
        outstanding = invoice.grand_total - allocated
        if outstanding > ZERO:
            items.append(
                {
                    "kind": "SALES",
                    "kind_label": _("فروش"),
                    "invoice": invoice,
                    "party": invoice.customer,
                    "total": invoice.grand_total,
                    "allocated": allocated,
                    "outstanding": outstanding,
                }
            )
    for invoice in purchase_invoices:
        allocated = purchase_allocated.get(invoice.id, ZERO)
        outstanding = invoice.grand_total - allocated
        if outstanding > ZERO:
            items.append(
                {
                    "kind": "PURCHASE",
                    "kind_label": _("خرید"),
                    "invoice": invoice,
                    "party": invoice.supplier,
                    "total": invoice.grand_total,
                    "allocated": allocated,
                    "outstanding": outstanding,
                }
            )
    items.sort(key=lambda row: (row["invoice"].invoice_date, row["invoice"].invoice_number))
    return items


def party_statement(company, party):
    """Invoices of one party with their allocations and open amounts."""
    from apps.purchases.models import PurchaseInvoice
    from apps.sales.models import SalesInvoice
    from apps.treasury.models import PaymentAllocation

    rows = []
    invoices = list(
        SalesInvoice.objects.filter(company=company, customer=party, status="POSTED")
    ) + list(PurchaseInvoice.objects.filter(company=company, supplier=party, status="POSTED"))
    for invoice in sorted(invoices, key=lambda inv: (inv.invoice_date, inv.invoice_number)):
        allocations = PaymentAllocation.objects.filter(
            status=PaymentAllocation.Status.ACTIVE,
            **{"sales_invoice" if hasattr(invoice, "customer_id") else "purchase_invoice": invoice},
        ).select_related("payment")
        allocated = allocated_amount(invoice)
        rows.append(
            {
                "invoice": invoice,
                "total": invoice.grand_total,
                "allocated": allocated,
                "outstanding": invoice.grand_total - allocated,
                "payment_status": invoice.payment_status,
                "allocations": list(allocations),
            }
        )
    return rows
