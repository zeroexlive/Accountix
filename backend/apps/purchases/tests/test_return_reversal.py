"""Purchase return reversal (Sprint 07): the returns matrix is complete —
a POSTED purchase return can be reversed, restoring stock, the payables
balance and the line's returnable quantity."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.inventory import reporting as inv_reporting
from apps.purchases import reporting as purchase_reporting
from apps.purchases import services
from apps.treasury.tests._helpers import build_world, post_purchase

D = Decimal


@pytest.fixture
def world(db):
    return build_world()


def _post_return(w, qty="3", number="PRET-1"):
    invoice = post_purchase(w)
    line = invoice.lines.get()
    ret = services.create_purchase_return(
        company=w.company,
        original_invoice=invoice,
        return_number=number,
        return_date=invoice.invoice_date,
        lines=[{"invoice_line": line, "quantity": D(qty)}],
    )
    ret = services.post_purchase_return(
        ret, gl_accounts={"inventory": w.inventory, "payables": w.ap}
    )
    return invoice, line, ret


@pytest.mark.django_db
def test_purchase_return_reversal_restores_stock_and_ap(world):
    w = world
    invoice, line, ret = _post_return(w)
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("7")
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("800")

    services.reverse_purchase_return(ret)
    ret.refresh_from_db()
    assert ret.status == "REVERSED"
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("10") and row["value"] == D("1000")
    # AP is back to the full invoice amount (1000 + 100 tax).
    assert purchase_reporting.supplier_balance(w.company, w.ap, w.supplier) == D("1100")


@pytest.mark.django_db
def test_purchase_return_reversal_rejected_twice_and_for_draft(world):
    w = world
    invoice, line, ret = _post_return(w)
    services.reverse_purchase_return(ret)
    with pytest.raises(ValidationError):
        services.reverse_purchase_return(ret)

    ret2 = services.create_purchase_return(
        company=w.company,
        original_invoice=invoice,
        return_number="PRET-2",
        return_date=invoice.invoice_date,
        lines=[{"invoice_line": line, "quantity": D("1")}],
    )
    with pytest.raises(ValidationError):
        services.reverse_purchase_return(ret2)  # still DRAFT


@pytest.mark.django_db
def test_return_reverse_return_again_same_quantity(world):
    """After a return is reversed its quantity no longer counts as
    returned (tallies sum POSTED returns only), so the same quantity can
    be returned again; over-return still applies to the live return."""
    w = world
    invoice, line, ret = _post_return(w, qty="3")
    services.reverse_purchase_return(ret)
    assert services.returned_quantity(line) == D("0")

    ret2 = services.create_purchase_return(
        company=w.company,
        original_invoice=invoice,
        return_number="PRET-2",
        return_date=invoice.invoice_date,
        lines=[{"invoice_line": line, "quantity": D("3")}],
    )
    ret2 = services.post_purchase_return(
        ret2, gl_accounts={"inventory": w.inventory, "payables": w.ap}
    )
    assert ret2.status == "POSTED"
    assert services.returned_quantity(line) == D("3")
    row = inv_reporting.stock_balance(w.company, w.warehouse, w.product)
    assert row["quantity"] == D("7")
