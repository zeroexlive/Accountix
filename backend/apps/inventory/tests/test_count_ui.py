"""Sprint 13 — stock counts through the UI + the draft-lines service.

Flow: create (the service snapshots every stockable product, counted
seeded with the snapshot) → type counted quantities on the count page
→ save through ``update_inventory_count_lines`` → post. The ADR-027
freeze rule is the centerpiece negative test: move the stock after
the snapshot and the post is rejected, with snapshot and live
quantities both visible on the page.
"""

from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.accounting import reporting as accounting_reporting
from apps.catalog.models import Product
from apps.inventory import reporting, services
from apps.inventory.models import InventoryCount
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db
D = Decimal


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="pw")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def _create_count_via_ui(client, w, count_date="2026-06-02"):
    resp = client.post(
        reverse("inventory_count_create"),
        {
            "company": str(w.company.pk),
            "warehouse": str(w.warehouse.pk),
            "count_date": count_date,
            "description": "",
        },
    )
    assert resp.status_code == 302
    return InventoryCount.objects.get(company=w.company)


def _save_payload(counted, unit_cost=""):
    return {
        "lines-TOTAL_FORMS": "1",
        "lines-INITIAL_FORMS": "1",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-counted_qty": counted,
        "lines-0-unit_cost": unit_cost,
    }


def test_count_ui_flow_with_variance_journal(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)  # stock 10 @ 100 → value 1000
    count = _create_count_via_ui(client, w)
    line = count.lines.get()
    assert line.system_qty == D("10") and line.counted_qty == D("10")

    detail = client.get(reverse("inventory_count_detail", args=[count.pk]))
    assert detail.context["rows"][0]["current_qty"] == D("10")

    resp = client.post(reverse("inventory_count_save", args=[count.pk]), _save_payload("8"))
    assert resp.status_code == 302
    line.refresh_from_db()
    assert line.counted_qty == D("8")

    resp = client.post(
        reverse("inventory_count_post", args=[count.pk]),
        {
            "inventory_account": str(w.inventory.pk),
            "variance_account": str(w.expense.pk),
        },
    )
    assert resp.status_code == 302
    count.refresh_from_db()
    assert count.status == "POSTED"
    balance = reporting.stock_balance(w.company, w.warehouse, w.product)
    assert balance["quantity"] == D("8") and balance["value"] == D("800")
    # Net variance −200: Dr variance (expense) 200 / Cr inventory GL 200.
    assert accounting_reporting.account_balance(w.company, w.expense) == D("200")
    assert accounting_reporting.account_balance(w.company, w.inventory) == D("800")
    assert count.journal_entry is not None


def test_count_ui_freeze_violation_rejects_post(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    count = _create_count_via_ui(client, w)
    post_sale(w)  # stock moves 10 → 6 after the snapshot

    resp = client.post(
        reverse("inventory_count_post", args=[count.pk]),
        {"inventory_account": "", "variance_account": ""},
        follow=True,
    )
    content = resp.content.decode()
    assert "از زمان شمارش تغییر کرده است" in content
    count.refresh_from_db()
    assert count.status == "DRAFT"
    balance = reporting.stock_balance(w.company, w.warehouse, w.product)
    assert balance["quantity"] == D("6")
    # The page shows both quantities so the user understands the freeze.
    detail = client.get(reverse("inventory_count_detail", args=[count.pk]))
    row = detail.context["rows"][0]
    assert row["line"].system_qty == D("10") and row["current_qty"] == D("6")


def test_count_ui_found_stock_with_unit_cost(client):
    w = build_world()
    _member_client(client, w.company)
    unit = w.product.base_unit
    found = Product.objects.create(company=w.company, sku="P-2", name="Found item", base_unit=unit)
    count = _create_count_via_ui(client, w)
    line = count.lines.get(product=found)
    assert line.system_qty == D("0")

    payload = {
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "2",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
    }
    ordered = list(count.lines.all())
    for idx, count_line in enumerate(ordered):
        if count_line.product_id == found.id:
            payload[f"lines-{idx}-counted_qty"] = "5"
            payload[f"lines-{idx}-unit_cost"] = "50"
        else:
            payload[f"lines-{idx}-counted_qty"] = str(count_line.counted_qty)
            payload[f"lines-{idx}-unit_cost"] = ""
    resp = client.post(reverse("inventory_count_save", args=[count.pk]), payload)
    assert resp.status_code == 302
    resp = client.post(
        reverse("inventory_count_post", args=[count.pk]),
        {"inventory_account": "", "variance_account": ""},
    )
    assert resp.status_code == 302
    balance = reporting.stock_balance(w.company, w.warehouse, found)
    assert balance["quantity"] == D("5") and balance["value"] == D("250")


def test_count_ui_non_member_gets_404(client):
    w = build_world()
    _member_client(client, w.company)
    post_purchase(w)
    count = _create_count_via_ui(client, w)
    other = build_world(company_name="Foreign Co")
    _member_client(client, other.company, username="outsider")
    assert client.get(reverse("inventory_count_detail", args=[count.pk])).status_code == 404
    resp = client.post(
        reverse("inventory_count_create"),
        {
            "company": str(w.company.pk),
            "warehouse": str(w.warehouse.pk),
            "count_date": "2026-06-02",
            "description": "",
        },
    )
    assert resp.status_code == 404
    assert InventoryCount.objects.filter(company=w.company).count() == 1


# ---------------------------------------------------------------------------
# update_inventory_count_lines — service level
# ---------------------------------------------------------------------------


def test_update_lines_rejects_posted_count_and_foreign_product():
    w = build_world()
    post_purchase(w)
    count = services.create_inventory_count(
        company=w.company,
        warehouse=w.warehouse,
        count_date=w.company.fiscal_periods.get().start_date,
        lines=[{"product": w.product, "counted_qty": D("10")}],
    )
    services.update_inventory_count_lines(
        count, lines=[{"product": w.product, "counted_qty": D("9")}]
    )
    assert count.lines.get().counted_qty == D("9")
    with pytest.raises(ValidationError):
        services.update_inventory_count_lines(
            count, lines=[{"product": w.product, "counted_qty": D("-1")}]
        )
    stranger = Product.objects.create(
        company=w.company, sku="P-9", name="Stranger", base_unit=w.product.base_unit
    )
    with pytest.raises(ValidationError):
        services.update_inventory_count_lines(
            count, lines=[{"product": stranger, "counted_qty": D("1")}]
        )
    services.post_inventory_count(count)
    with pytest.raises(ValidationError):
        services.update_inventory_count_lines(
            count, lines=[{"product": w.product, "counted_qty": D("1")}]
        )
