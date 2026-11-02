from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from apps.catalog import services
from apps.catalog.models import Product, ProductCategory, ProductUnitConversion, Unit
from apps.organizations.models import Company

D = Decimal


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other")


@pytest.fixture
def pcs(db, company):
    return Unit.objects.create(company=company, code="PCS", name="Piece")


@pytest.fixture
def box(db, company):
    return Unit.objects.create(company=company, code="BOX", name="Box")


@pytest.fixture
def product(db, company, pcs):
    return Product.objects.create(company=company, sku="P-1", name="Widget", base_unit=pcs)


@pytest.mark.django_db
def test_sku_unique_per_company(company, pcs):
    Product.objects.create(company=company, sku="X", name="a", base_unit=pcs)
    with pytest.raises(IntegrityError):
        Product.objects.create(company=company, sku="X", name="b", base_unit=pcs)


@pytest.mark.django_db
def test_same_sku_allowed_in_other_company(company, other_company, pcs):
    other_unit = Unit.objects.create(company=other_company, code="PCS", name="Piece")
    Product.objects.create(company=company, sku="X", name="a", base_unit=pcs)
    Product.objects.create(company=other_company, sku="X", name="b", base_unit=other_unit)


@pytest.mark.django_db
def test_product_rejects_cross_company_unit(company, other_company, product):
    foreign_unit = Unit.objects.create(company=other_company, code="KG", name="Kilo")
    product.base_unit = foreign_unit
    with pytest.raises(ValidationError):
        product.full_clean()


@pytest.mark.django_db
def test_category_cycle_rejected(company):
    a = ProductCategory.objects.create(company=company, code="A", name="A")
    b = ProductCategory.objects.create(company=company, code="B", name="B", parent=a)
    a.parent = b
    with pytest.raises(ValidationError):
        a.full_clean()


@pytest.mark.django_db
def test_conversion_direct_and_inverse(company, product, pcs, box):
    ProductUnitConversion.objects.create(
        company=company, product=product, from_unit=box, to_unit=pcs, factor=D("12")
    )
    assert services.convert_quantity(
        product=product, quantity=D("2"), from_unit=box, to_unit=pcs
    ) == D("24")
    assert services.convert_quantity(
        product=product, quantity=D("24"), from_unit=pcs, to_unit=box
    ) == D("2")
    assert services.convert_quantity(
        product=product, quantity=D("5"), from_unit=pcs, to_unit=pcs
    ) == D("5")


@pytest.mark.django_db
def test_conversion_missing_rejected(company, product, pcs, box):
    with pytest.raises(ValidationError):
        services.convert_quantity(product=product, quantity=D("1"), from_unit=box, to_unit=pcs)


@pytest.mark.django_db
def test_conversion_rejects_cross_company_product(company, other_company, pcs, box):
    foreign_product = Product.objects.create(
        company=other_company,
        sku="F-1",
        name="Foreign",
        base_unit=Unit.objects.create(company=other_company, code="PCS", name="Piece"),
    )
    conv = ProductUnitConversion(
        company=company, product=foreign_product, from_unit=box, to_unit=pcs, factor=D("10")
    )
    with pytest.raises(ValidationError):
        conv.full_clean()
