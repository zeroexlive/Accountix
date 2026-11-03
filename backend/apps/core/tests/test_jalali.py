"""Sprint 13 — Jalali display layer (ADR-040).

Conversion pairs are cross-checked against the jdatetime reference
implementation: 1404 is a common year (Esfand has 29 days), so
2026-03-20 is 1404-12-29, the last day of 1404. Display is Jalali in
``YYYY/MM/DD`` with Latin digits (the UI's digit convention); storage
and inputs stay Gregorian.
"""

import datetime

import pytest
from django.contrib.auth import get_user_model
from django.template import Context, Template
from django.urls import reverse

from apps.core.templatetags.jalali import to_jalali
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db

PAIRS = [
    (datetime.date(2026, 3, 21), "1405/01/01"),  # Nowruz 1405
    (datetime.date(2026, 3, 20), "1404/12/29"),  # last day of common-year 1404
    (datetime.date(2024, 3, 20), "1403/01/01"),  # Nowruz 1403
    (datetime.date(2025, 1, 1), "1403/10/12"),
    (datetime.date(2026, 6, 1), "1405/03/11"),
    (datetime.date(2026, 12, 31), "1405/10/10"),
]


@pytest.mark.parametrize("gregorian,expected", PAIRS)
def test_to_jalali_known_pairs(gregorian, expected):
    assert to_jalali(gregorian) == expected


def test_to_jalali_accepts_datetime_and_none():
    moment = datetime.datetime(2026, 3, 21, 23, 59, 59)
    assert to_jalali(moment) == "1405/01/01"
    assert to_jalali(None) == ""
    assert to_jalali("not-a-date") == "not-a-date"


def test_jalali_filter_renders_through_template():
    template = Template("{% load jalali %}{{ value|jalali }}")
    rendered = template.render(Context({"value": datetime.date(2026, 3, 20)}))
    assert rendered == "1404/12/29"
    # None stays empty so |default chains keep working.
    template = Template('{% load jalali %}{{ value|jalali|default:"—" }}')
    assert template.render(Context({"value": None})) == "—"


def test_invoice_detail_page_shows_jalali_not_gregorian(client):
    w = build_world()
    user = User.objects.create_user(username="boss", password="pw")
    CompanyMembership.objects.create(user=user, company=w.company, role="OWNER")
    client.force_login(user)
    post_purchase(w)
    sale = post_sale(w)  # invoice_date = 2026-06-01 → 1405/03/11
    resp = client.get(reverse("sales_invoice_detail", args=[sale.pk]))
    content = resp.content.decode()
    # The invoice's own date renders Jalali. (Journal-entry descriptions
    # further down the page are service-generated text, not date
    # displays, and keep their embedded ISO dates — ADR-040.)
    assert "تاریخ: 1405/03/11" in content
    assert "تاریخ: 2026-06-01" not in content


def test_invoice_print_shows_jalali(client):
    w = build_world()
    user = User.objects.create_user(username="boss2", password="pw")
    CompanyMembership.objects.create(user=user, company=w.company, role="OWNER")
    client.force_login(user)
    post_purchase(w)
    sale = post_sale(w)
    resp = client.get(reverse("sales_invoice_print", args=[sale.pk]))
    content = resp.content.decode()
    assert "1405/03/11" in content
    assert "2026-06-01" not in content
