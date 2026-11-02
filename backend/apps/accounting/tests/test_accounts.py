import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.urls import reverse

from apps.accounting.models import Account
from apps.organizations.models import Company, CompanyMembership

User = get_user_model()


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other")


def make(company, code, **kw):
    defaults = {"name": f"A{code}", "account_type": "ASSET", "normal_balance": "DEBIT"}
    defaults.update(kw)
    return Account(company=company, code=code, **defaults)


@pytest.mark.django_db
def test_account_code_unique_per_company(company):
    make(company, "1000").save()
    with pytest.raises(IntegrityError):
        make(company, "1000").save()


@pytest.mark.django_db
def test_same_code_allowed_in_other_company(company, other_company):
    make(company, "1000").save()
    make(other_company, "1000").save()  # must not raise


@pytest.mark.django_db
def test_self_parent_rejected(company):
    a = make(company, "1000")
    a.save()
    a.parent = a
    with pytest.raises(ValidationError):
        a.full_clean()


@pytest.mark.django_db
def test_cross_company_parent_rejected(company, other_company):
    parent = make(other_company, "9000")
    parent.save()
    child = make(company, "1000", parent=parent)
    with pytest.raises(ValidationError):
        child.full_clean()


@pytest.mark.django_db
def test_cycle_rejected(company):
    a = make(company, "1000")
    a.save()
    b = make(company, "1100", parent=a)
    b.save()
    a.parent = b
    with pytest.raises(ValidationError):
        a.full_clean()


@pytest.mark.django_db
def test_valid_hierarchy_ok(company):
    a = make(company, "1000")
    a.full_clean()
    a.save()
    b = make(company, "1100", parent=a)
    b.full_clean()
    b.save()
    assert list(a.children.all()) == [b]


@pytest.mark.django_db
def test_account_list_isolated_by_membership(client, company):
    make(company, "1000").save()
    user = User.objects.create_user(username="u1", password="x")
    client.force_login(user)  # not a member
    resp = client.get(reverse("account_list"))
    assert b"1000" not in resp.content
    CompanyMembership.objects.create(company=company, user=user, role="ACCOUNTANT")
    resp = client.get(reverse("account_list"))
    assert b"1000" in resp.content
