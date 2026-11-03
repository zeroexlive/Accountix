"""Read-only statement pages (Sprint 07 UI): income statement, balance
sheet, and the stock-count list render for member companies only."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.inventory import services as inv_services
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import D, build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company):
    user = User.objects.create_user(username="boss", password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def test_statement_pages_render_and_show_numbers(client):
    w = build_world()
    post_purchase(w)
    post_sale(w)
    client = _member_client(client, w.company)

    resp = client.get(reverse("income_statement"), {"company": w.company.pk})
    assert resp.status_code == 200
    assert D("1000") == resp.context["result"]["revenue_total"]
    assert resp.context["result"]["net_income"] == D("600")

    resp = client.get(reverse("balance_sheet"), {"company": w.company.pk})
    assert resp.status_code == 200
    assert resp.context["result"]["is_balanced"]

    # A foreign company id is a 404, not a data leak.
    other = build_world(company_name="Other Co")
    resp = client.get(reverse("balance_sheet"), {"company": other.company.pk})
    assert resp.status_code == 404


def test_count_list_page_shows_posted_count(client):
    w = build_world()
    post_purchase(w)
    count = inv_services.create_inventory_count(
        company=w.company,
        warehouse=w.warehouse,
        count_date=w.company.fiscal_periods.get().start_date,
        lines=[{"product": w.product, "counted_qty": D("9")}],
    )
    inv_services.post_inventory_count(count)
    client = _member_client(client, w.company)
    resp = client.get(reverse("inventory_counts"))
    assert resp.status_code == 200
    # Sprint 30 (ADR-055): the list renders the translated status
    # label («ثبت‌شده»), not the raw POSTED code.
    assert "ثبت‌شده".encode() in resp.content
    assert b"POSTED" not in resp.content
    assert b"P-1" in resp.content


def test_statement_pages_require_login(client):
    assert client.get(reverse("income_statement")).status_code == 302
    assert client.get(reverse("balance_sheet")).status_code == 302
    assert client.get(reverse("inventory_counts")).status_code == 302
