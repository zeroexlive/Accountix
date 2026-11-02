import pytest
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.urls import reverse

from apps.organizations.models import Company, CompanyMembership
from apps.parties.models import Party, PartyAddress, PartyContact
from apps.parties.services import require_supplier

User = get_user_model()


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


@pytest.fixture
def other_company(db):
    return Company.objects.create(name="Other")


@pytest.mark.django_db
def test_party_code_unique_per_company(company):
    Party.objects.create(company=company, code="SUP-1", name="Supplier One")
    with pytest.raises(IntegrityError):
        Party.objects.create(company=company, code="SUP-1", name="Duplicate")


@pytest.mark.django_db
def test_party_code_reusable_in_another_company(company, other_company):
    Party.objects.create(company=company, code="SUP-1", name="Supplier One")
    other = Party.objects.create(company=other_company, code="SUP-1", name="Other Supplier")
    assert other.pk is not None


@pytest.mark.django_db
def test_party_kind_flags(company):
    both = Party.objects.create(company=company, code="B-1", name="Both", kind="BOTH")
    customer = Party.objects.create(company=company, code="C-1", name="Cust", kind="CUSTOMER")
    assert both.is_supplier and both.is_customer
    assert customer.is_customer and not customer.is_supplier


@pytest.mark.django_db
def test_contacts_and_addresses_attach_to_party(company):
    party = Party.objects.create(company=company, code="SUP-1", name="Supplier")
    PartyContact.objects.create(party=party, full_name="Ms Buyer", is_primary=True)
    PartyAddress.objects.create(party=party, label="HQ", city="Tehran", postal_code="12345")
    assert party.contacts.count() == 1
    assert party.addresses.get().city == "Tehran"


@pytest.mark.django_db
def test_require_supplier_rejects_customer_and_cross_company(company, other_company):
    from django.core.exceptions import ValidationError

    customer = Party.objects.create(company=company, code="C-1", name="Cust", kind="CUSTOMER")
    with pytest.raises(ValidationError):
        require_supplier(company, customer)
    foreign = Party.objects.create(company=other_company, code="S-9", name="Foreign")
    with pytest.raises(ValidationError):
        require_supplier(company, foreign)


@pytest.mark.django_db
def test_party_list_view_company_isolation(client, company, other_company):
    user = User.objects.create_user(username="u1", password="pw")
    CompanyMembership.objects.create(company=company, user=user, role="OWNER")
    Party.objects.create(company=company, code="MINE", name="Mine")
    Party.objects.create(company=other_company, code="THEIRS", name="Theirs")
    client.force_login(user)
    response = client.get(reverse("party_list"))
    content = response.content.decode()
    assert "MINE" in content
    assert "THEIRS" not in content
