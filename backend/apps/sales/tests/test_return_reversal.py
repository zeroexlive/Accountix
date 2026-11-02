"""Sales return reversal (Sprint 07): a POSTED sales return can be
reversed, taking the restored goods back out of stock and restoring
revenue/COGS/receivables; the returnable quantity is freed again."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.accounting import reporting as acct_reporting
from apps.inventory import reporting as inv_reporting
from apps.sales import reporting as sales_reporting
from apps.sales import services
from apps.treasury.tests._helpers import build_world, post_purchase, post_sale

D = Decimal


def GL(w):
    return {
        "receivables": w.ar,
        "revenue": w.revenue,
        "tax_payable": w.tax_out,
        "cogs": w.cogs,
        "inventory": w.inventory,
    }


@pytest.fixture
def world(db):
    return build_world()


def _post_return(w, qty="2", number="SRET-1"):
    post_purchase(w)
    sale = post_sale(w)
    line = sale.lines.get()
    ret = services.create_sales_return(
        company=w.company,
        original_invoice=sale,
        return_number=number,
        return_date=sale.invoice_date,
        lines=[{"invoice_line": line, "quantity": D(qty)}],
    )
    ret = services.post_sales_return(ret, gl_accounts=GL(w))
    return sale, line, ret


@pytest.mark.django_db
def test_sales_return_reversal_restores_everything(world):
    w = world
    sale, line, ret = _post_return(w)
    # After the sale of 4 and a return of 2: stock 8, COGS 200, AR 550.
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("8")
    assert acct_reporting.account_balance(w.company, w.cogs) == D("200")
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("550")

    services.reverse_sales_return(ret)
    ret.refresh_from_db()
    assert ret.status == "REVERSED"
    # Goods are out again, COGS and AR are back to the full sale.
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("6") and row["value"] == D("600")
    assert acct_reporting.account_balance(w.company, w.cogs) == D("400")
    assert sales_reporting.customer_balance(w.company, w.ar, w.customer) == D("1100")
    assert acct_reporting.account_balance(w.company, w.revenue) == D("-1000")


@pytest.mark.django_db
def test_sales_return_reversal_rejected_twice_and_for_draft(world):
    w = world
    sale, line, ret = _post_return(w)
    services.reverse_sales_return(ret)
    with pytest.raises(ValidationError):
        services.reverse_sales_return(ret)

    ret2 = services.create_sales_return(
        company=w.company,
        original_invoice=sale,
        return_number="SRET-2",
        return_date=sale.invoice_date,
        lines=[{"invoice_line": line, "quantity": D("1")}],
    )
    with pytest.raises(ValidationError):
        services.reverse_sales_return(ret2)  # still DRAFT


@pytest.mark.django_db
def test_return_reverse_return_again_same_quantity(world):
    w = world
    sale, line, ret = _post_return(w, qty="2")
    services.reverse_sales_return(ret)
    assert services.returned_quantity(line) == D("0")

    ret2 = services.create_sales_return(
        company=w.company,
        original_invoice=sale,
        return_number="SRET-2",
        return_date=sale.invoice_date,
        lines=[{"invoice_line": line, "quantity": D("2")}],
    )
    ret2 = services.post_sales_return(ret2, gl_accounts=GL(w))
    assert ret2.status == "POSTED"
    assert services.returned_quantity(line) == D("2")
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("8")
