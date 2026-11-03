"""Sprint 12 — catalog master data through the UI (scope B, ADR-039).

Unit / category / warehouse / product creation and product edit via
the forms; pickers are company-scoped server-side, the model
``clean()`` is the final cross-company guard, and a POST naming a
company outside the user's memberships is a 404.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.catalog.models import Product, ProductCategory, Unit
from apps.inventory.models import Warehouse
from apps.organizations.models import CompanyMembership
from apps.treasury.tests._helpers import build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


def _member_client(client, company, username="boss"):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role="OWNER")
    client.force_login(user)
    return client


def test_unit_category_warehouse_create(client):
    w = build_world()
    _member_client(client, w.company)
    resp = client.post(
        reverse("unit_create"),
        {"company": str(w.company.pk), "code": "KG", "name": "Kilogram", "is_active": "on"},
    )
    assert resp.status_code == 302
    unit = Unit.objects.get(company=w.company, code="KG")

    resp = client.post(
        reverse("category_create"),
        {
            "company": str(w.company.pk),
            "parent": "",
            "code": "CAT-1",
            "name": "General",
            "is_active": "on",
        },
    )
    assert resp.status_code == 302
    category = ProductCategory.objects.get(company=w.company, code="CAT-1")

    resp = client.post(
        reverse("warehouse_create"),
        {"company": str(w.company.pk), "code": "WH2", "name": "Second", "is_active": "on"},
    )
    assert resp.status_code == 302
    assert Warehouse.objects.filter(company=w.company, code="WH2").exists()
    assert unit.pk and category.pk


def test_product_create_and_edit(client):
    w = build_world()
    _member_client(client, w.company)
    unit = Unit.objects.get(company=w.company, code="PCS")
    resp = client.post(
        reverse("product_create"),
        {
            "company": str(w.company.pk),
            "category": "",
            "base_unit": str(unit.pk),
            "sku": "P-9",
            "barcode": "",
            "name": "Gadget",
            "description": "",
            "is_stockable": "on",
            "is_active": "on",
            "min_stock_level": "0",
            "default_purchase_price": "",
            "default_sale_price": "",
        },
    )
    assert resp.status_code == 302
    product = Product.objects.get(company=w.company, sku="P-9")
    assert product.base_unit_id == unit.pk

    resp = client.post(
        reverse("product_edit", args=[product.pk]),
        {
            "company": str(w.company.pk),
            "category": "",
            "base_unit": str(unit.pk),
            "sku": "P-9",
            "barcode": "",
            "name": "Gadget Pro",
            "description": "",
            "is_stockable": "on",
            "is_active": "on",
            "min_stock_level": "1",
            "default_purchase_price": "",
            "default_sale_price": "",
        },
    )
    assert resp.status_code == 302
    product.refresh_from_db()
    assert product.name == "Gadget Pro"
    assert product.company_id == w.company.pk


def test_product_create_cross_company_unit_rejected(client):
    w = build_world()
    other = build_world(company_name="Other Co")
    _member_client(client, w.company)
    foreign_unit = Unit.objects.get(company=other.company, code="PCS")
    resp = client.post(
        reverse("product_create"),
        {
            "company": str(w.company.pk),
            "category": "",
            "base_unit": str(foreign_unit.pk),
            "sku": "P-X",
            "barcode": "",
            "name": "Nope",
            "description": "",
            "is_stockable": "on",
            "is_active": "on",
            "min_stock_level": "0",
            "default_purchase_price": "",
            "default_sale_price": "",
        },
    )
    assert resp.status_code == 200
    assert not Product.objects.filter(company=w.company, sku="P-X").exists()


def test_master_data_create_non_member_company_is_404(client):
    w = build_world()
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    for url_name, payload in [
        ("unit_create", {"company": str(w.company.pk), "code": "KG", "name": "Kilo"}),
        ("warehouse_create", {"company": str(w.company.pk), "code": "WH9", "name": "Nope"}),
        (
            "category_create",
            {"company": str(w.company.pk), "parent": "", "code": "C9", "name": "Nope"},
        ),
    ]:
        resp = client.post(reverse(url_name), payload)
        assert resp.status_code == 404, url_name
    assert not Unit.objects.filter(company=w.company, code="KG").exists()
    assert not Warehouse.objects.filter(company=w.company, code="WH9").exists()
