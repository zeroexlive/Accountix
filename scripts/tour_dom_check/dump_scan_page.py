"""Scan page dumper for the DOM check (Sprint 31, ADR-060).

Renders the real sales invoice create page from a minimal world
with TWO barcoded products (the scan harness needs two distinct
products to exercise fill-empty-line and increment paths):

    TOUR_DUMP_DIR=/tmp/tour-harness/pages \
        pytest scripts/tour_dom_check/dump_scan_page.py
"""

import os
from pathlib import Path

import pytest
from apps.catalog.models import Product, Unit
from apps.organizations.models import Company, CompanyMembership
from django.contrib.auth import get_user_model
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_dump_scan_page(client, db, tmp_path):
    outdir = Path(os.environ.get("TOUR_DUMP_DIR", str(tmp_path / "pages")))
    outdir.mkdir(parents=True, exist_ok=True)
    company = Company.objects.create(name="Scan Dump Co")
    unit = Unit.objects.create(company=company, code="PCS", name="Piece")
    Product.objects.create(
        company=company,
        sku="SKU-A",
        barcode="111",
        name="Product A",
        base_unit=unit,
        default_sale_price="250.00",
        default_purchase_price="100.00",
    )
    Product.objects.create(
        company=company,
        sku="SKU-B",
        barcode="222",
        name="Product B",
        base_unit=unit,
        default_sale_price="500.00",
        default_purchase_price="200.00",
    )
    user = get_user_model().objects.create_user(username="boss", password="Str0ng!Pass1")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    resp = client.get(reverse("sales_invoice_create"), {"company": company.pk})
    assert resp.status_code == 200
    html = resp.content.decode()
    assert "data-scan-root" in html
    (outdir / "sales_invoice_create.scan.html").write_text(html, encoding="utf-8")
