from datetime import date

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.organizations.models import Company, CompanyMembership, FiscalPeriod, FiscalYear

User = get_user_model()


@pytest.fixture
def owner(db):
    return User.objects.create_user(username="owner", password="x")


@pytest.fixture
def outsider(db):
    return User.objects.create_user(username="outsider", password="x")


@pytest.fixture
def company(db, owner):
    c = Company.objects.create(name="Acme")
    CompanyMembership.objects.create(company=c, user=owner, role="OWNER")
    return c


@pytest.mark.django_db
def test_company_create_view_grants_owner_membership(client, owner):
    client.force_login(owner)
    resp = client.post(reverse("company_create"), {"name": "NewCo", "default_currency": "IRR"})
    assert resp.status_code == 302
    c = Company.objects.get(name="NewCo")
    assert CompanyMembership.objects.filter(company=c, user=owner, role="OWNER").exists()


@pytest.mark.django_db
def test_company_isolation_list(client, owner, outsider, company):
    client.force_login(outsider)
    resp = client.get(reverse("company_list"))
    assert b"Acme" not in resp.content
    client.force_login(owner)
    resp = client.get(reverse("company_list"))
    assert b"Acme" in resp.content


@pytest.mark.django_db
def test_company_detail_denied_for_non_member(client, outsider, company):
    client.force_login(outsider)
    resp = client.get(reverse("company_detail", args=[company.pk]))
    assert resp.status_code == 404  # filtered queryset — does not leak existence


@pytest.mark.django_db
def test_membership_unique_per_company_user(owner, company):
    with pytest.raises(IntegrityError):
        CompanyMembership.objects.create(company=company, user=owner)


@pytest.mark.django_db
def test_fiscal_year_valid(company):
    fy = FiscalYear(
        company=company, name="1405", start_date=date(2026, 3, 21), end_date=date(2027, 3, 20)
    )
    fy.full_clean()
    fy.save()
    assert fy.pk


@pytest.mark.django_db
def test_fiscal_year_end_before_start_rejected(company):
    fy = FiscalYear(
        company=company, name="bad", start_date=date(2027, 1, 1), end_date=date(2026, 1, 1)
    )
    with pytest.raises(ValidationError):
        fy.full_clean()


@pytest.mark.django_db
def test_fiscal_year_overlap_rejected(company):
    FiscalYear.objects.create(
        company=company, name="a", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    fy = FiscalYear(
        company=company, name="b", start_date=date(2026, 6, 1), end_date=date(2027, 5, 31)
    )
    with pytest.raises(ValidationError):
        fy.full_clean()


@pytest.mark.django_db
def test_fiscal_year_overlap_allowed_for_other_company(owner):
    other = Company.objects.create(name="Other")
    FiscalYear.objects.create(
        company=other, name="a", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    fy = FiscalYear(
        company=Company.objects.create(name="Third"),
        name="b",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 5, 31),
    )
    fy.full_clean()  # no overlap within its own company


@pytest.fixture
def fiscal_year(db, company):
    return FiscalYear.objects.create(
        company=company, name="1405", start_date=date(2026, 3, 21), end_date=date(2027, 3, 20)
    )


@pytest.mark.django_db
def test_fiscal_period_inside_year_ok(company, fiscal_year):
    p = FiscalPeriod(
        company=company,
        fiscal_year=fiscal_year,
        name="P1",
        start_date=date(2026, 3, 21),
        end_date=date(2026, 4, 20),
    )
    p.full_clean()
    p.save()
    assert p.pk


@pytest.mark.django_db
def test_fiscal_period_outside_year_rejected(company, fiscal_year):
    p = FiscalPeriod(
        company=company,
        fiscal_year=fiscal_year,
        name="bad",
        start_date=date(2027, 3, 21),
        end_date=date(2027, 4, 20),
    )
    with pytest.raises(ValidationError):
        p.full_clean()


@pytest.mark.django_db
def test_fiscal_period_overlap_rejected(company, fiscal_year):
    FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fiscal_year,
        name="P1",
        start_date=date(2026, 3, 21),
        end_date=date(2026, 4, 20),
    )
    p = FiscalPeriod(
        company=company,
        fiscal_year=fiscal_year,
        name="P2",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 20),
    )
    with pytest.raises(ValidationError):
        p.full_clean()
