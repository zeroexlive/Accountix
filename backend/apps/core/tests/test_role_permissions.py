"""Sprint 25 — role-permission enforcement (ADR-050).

The matrix, proven end to end: every role reads; OPERATE roles write
documents; only OWNER/ADMIN administer (fiscal structure, closing,
opening balances); a non-member still gets 404 everywhere (never a
403 — existence must not leak); roles resolve per company, so the
same user can own one company and merely view another.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from apps.accounting import services as accounting_services
from apps.accounting.models import Account, JournalEntry
from apps.core.access import (
    ADMINISTER_ROLES,
    GOVERN_ROLES,
    OPERATE_ROLES,
    READ_ROLES,
    membership_for,
    role_for,
)
from apps.organizations.models import Company, CompanyMembership, FiscalYear
from apps.parties.models import Party
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db

ALL_ROLES = [role.value for role in CompanyMembership.Role]


def _user_with_role(company, role, username):
    user = User.objects.create_user(username=username, password="x")
    CompanyMembership.objects.create(user=user, company=company, role=role)
    return user


def _draft_entry(w):
    return accounting_services.create_journal_draft(
        company=w.company,
        entry_date=DAY,
        lines=[
            {"account": w.cash, "debit": D("10"), "credit": D("0")},
            {"account": w.revenue, "debit": D("0"), "credit": D("10")},
        ],
    )


def _journal_payload(w):
    return {
        "company": str(w.company.pk),
        "entry_date": DAY.isoformat(),
        "description": "role test",
        "idempotency_key": "",
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": str(w.cash.pk),
        "lines-0-debit": "10",
        "lines-0-credit": "0",
        "lines-0-description": "",
        "lines-0-party": "",
        "lines-1-account": str(w.revenue.pk),
        "lines-1-debit": "0",
        "lines-1-credit": "10",
        "lines-1-description": "",
        "lines-1-party": "",
    }


# ---------------------------------------------------------------------------
# The tiers themselves
# ---------------------------------------------------------------------------


def test_tiers_are_pinned_to_the_model_choices():
    assert set(READ_ROLES) == set(ALL_ROLES)
    assert set(OPERATE_ROLES) == set(ALL_ROLES) - {"VIEWER"}
    assert set(ADMINISTER_ROLES) == {"OWNER", "ADMIN"}
    assert set(GOVERN_ROLES) == {"OWNER"}
    field = CompanyMembership._meta.get_field("role")
    assert field.default == CompanyMembership.Role.VIEWER


def test_membership_lookup_ignores_inactive_rows():
    w = build_world()
    user = User.objects.create_user(username="ghost", password="x")
    CompanyMembership.objects.create(user=user, company=w.company, role="OWNER", is_active=False)
    assert membership_for(user, w.company) is None
    assert role_for(user, w.company) is None


# ---------------------------------------------------------------------------
# READ tier — every member, every role
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", ALL_ROLES)
def test_every_role_can_read(client, role):
    w = build_world()
    entry = _draft_entry(w)
    user = _user_with_role(w.company, role, f"reader-{role}")
    client.force_login(user)
    assert client.get(reverse("sales_invoice_list")).status_code == 200
    assert client.get(reverse("journal_detail", args=[entry.pk])).status_code == 200
    assert client.get(reverse("dashboard")).status_code == 200


# ---------------------------------------------------------------------------
# OPERATE tier — the viewer reads but cannot write; nothing persists
# ---------------------------------------------------------------------------


def test_viewer_operate_posts_are_403_and_persist_nothing(client):
    w = build_world()
    entry = _draft_entry(w)
    viewer = _user_with_role(w.company, "VIEWER", "viewer")
    client.force_login(viewer)

    resp = client.post(reverse("journal_create"), _journal_payload(w))
    assert resp.status_code == 403
    assert "دسترسی مجاز نیست" in resp.content.decode()  # the Persian 403 page
    assert JournalEntry.objects.filter(company=w.company).count() == 1  # only the seed draft

    resp = client.post(reverse("journal_post", args=[entry.pk]))
    assert resp.status_code == 403
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.DRAFT

    resp = client.post(
        reverse("party_create"),
        {"company": str(w.company.pk), "kind": "CUSTOMER", "code": "NEW-1", "name": "New"},
    )
    assert resp.status_code == 403
    assert not Party.objects.filter(company=w.company, code="NEW-1").exists()


@pytest.mark.parametrize("role", ["ACCOUNTANT", "SALES", "CASHIER", "WAREHOUSE"])
def test_operational_roles_can_operate(client, role):
    w = build_world()
    user = _user_with_role(w.company, role, f"op-{role}")
    client.force_login(user)
    resp = client.post(reverse("journal_create"), _journal_payload(w))
    assert resp.status_code == 302
    entry = JournalEntry.objects.get(company=w.company)
    resp = client.post(reverse("journal_post", args=[entry.pk]))
    assert resp.status_code == 302
    entry.refresh_from_db()
    assert entry.status == JournalEntry.Status.POSTED


# ---------------------------------------------------------------------------
# ADMINISTER tier — operate roles stop here; owner/admin pass
# ---------------------------------------------------------------------------


def _fiscal_year_payload(w, name="FY2027"):
    return {
        "company": str(w.company.pk),
        "name": name,
        "start_date": "2027-01-01",
        "end_date": "2027-12-31",
        "status": "OPEN",
    }


def test_accountant_cannot_administer(client):
    w = build_world()
    period = w.company.fiscal_periods.get()
    accountant = _user_with_role(w.company, "ACCOUNTANT", "acc")
    client.force_login(accountant)

    resp = client.post(reverse("fiscal_year_create"), _fiscal_year_payload(w))
    assert resp.status_code == 403
    assert not FiscalYear.objects.filter(company=w.company, name="FY2027").exists()

    # The close page itself is administer-only, on every method.
    assert client.get(reverse("fiscal_period_close", args=[period.pk])).status_code == 403

    resp = client.post(
        reverse("account_create"),
        {
            "company": str(w.company.pk),
            "code": "9999",
            "name": "Nope",
            "account_type": "ASSET",
            "normal_balance": "DEBIT",
            "is_postable": "on",
            "is_active": "on",
        },
    )
    assert resp.status_code == 403
    assert not Account.objects.filter(company=w.company, code="9999").exists()


@pytest.mark.parametrize("role", ["OWNER", "ADMIN"])
def test_top_tier_can_administer(client, role):
    w = build_world()
    user = _user_with_role(w.company, role, f"top-{role}")
    client.force_login(user)
    resp = client.post(reverse("fiscal_year_create"), _fiscal_year_payload(w))
    assert resp.status_code == 302
    assert FiscalYear.objects.filter(company=w.company, name="FY2027").exists()
    period = w.company.fiscal_periods.get()
    assert client.get(reverse("fiscal_period_close", args=[period.pk])).status_code == 200


# ---------------------------------------------------------------------------
# Service-layer defense in depth (closing / opening balances)
# ---------------------------------------------------------------------------


def _equity(company):
    return Account.objects.create(
        company=company,
        code="3100",
        name="Retained earnings",
        account_type="EQUITY",
        normal_balance="CREDIT",
        is_postable=True,
        is_active=True,
    )


def test_closing_services_assert_the_role_themselves():
    w = build_world()
    retained = _equity(w.company)
    period = w.company.fiscal_periods.get()
    year = w.company.fiscal_years.get()
    accountant = _user_with_role(w.company, "ACCOUNTANT", "svc-acc")
    admin = _user_with_role(w.company, "ADMIN", "svc-admin")

    with pytest.raises(PermissionDenied):
        accounting_services.close_fiscal_period(
            company=w.company, period=period, retained_earnings=retained, user=accountant
        )
    period.refresh_from_db()
    assert period.status == "OPEN"

    with pytest.raises(PermissionDenied):
        accounting_services.post_opening_balance(
            company=w.company,
            fiscal_year=year,
            lines=[{"account": w.cash, "debit": D("5"), "credit": D("0")}],
            offset_account=retained,
            user=accountant,
        )

    # user=None stays the trusted internal path; an ADMINISTER user passes.
    accounting_services.close_fiscal_period(
        company=w.company, period=period, retained_earnings=retained, user=admin
    )
    period.refresh_from_db()
    assert period.status == "CLOSED"
    with pytest.raises(PermissionDenied):
        accounting_services.reopen_fiscal_period(company=w.company, period=period, user=accountant)


# ---------------------------------------------------------------------------
# Isolation: non-members get 404, never 403
# ---------------------------------------------------------------------------


def test_non_member_gets_404_on_read_and_write(client):
    w = build_world()
    entry = _draft_entry(w)
    outsider = User.objects.create_user(username="outsider", password="x")
    client.force_login(outsider)
    assert client.get(reverse("journal_detail", args=[entry.pk])).status_code == 404
    assert client.post(reverse("journal_post", args=[entry.pk])).status_code == 404
    resp = client.post(
        reverse("party_create"),
        {"company": str(w.company.pk), "kind": "CUSTOMER", "code": "X-1", "name": "X"},
    )
    assert resp.status_code == 404
    assert not Party.objects.filter(company=w.company, code="X-1").exists()


# ---------------------------------------------------------------------------
# Per-company resolution: OWNER of A, VIEWER of B
# ---------------------------------------------------------------------------


def test_roles_resolve_per_company(client):
    a = build_world(company_name="Alpha")
    b = build_world(company_name="Beta")
    entry_a = _draft_entry(a)
    entry_b = _draft_entry(b)
    dual = User.objects.create_user(username="dual", password="x")
    CompanyMembership.objects.create(user=dual, company=a.company, role="OWNER")
    CompanyMembership.objects.create(user=dual, company=b.company, role="VIEWER")
    client.force_login(dual)

    assert client.post(reverse("journal_post", args=[entry_a.pk])).status_code == 302
    entry_a.refresh_from_db()
    assert entry_a.status == JournalEntry.Status.POSTED

    assert client.get(reverse("journal_detail", args=[entry_b.pk])).status_code == 200
    assert client.post(reverse("journal_post", args=[entry_b.pk])).status_code == 403
    entry_b.refresh_from_db()
    assert entry_b.status == JournalEntry.Status.DRAFT


# ---------------------------------------------------------------------------
# The setup-created admin (OWNER) is unaffected
# ---------------------------------------------------------------------------


def test_setup_admin_can_operate_and_administer(client):
    resp = client.post(
        reverse("setup"),
        {
            "username": "admin",
            "password1": "Tr7!qzvx-2941",
            "password2": "Tr7!qzvx-2941",
            "company_name": "شرکت نمونه",
        },
    )
    assert resp.status_code == 302
    company = Company.objects.get(name="شرکت نمونه")
    resp = client.post(
        reverse("fiscal_year_create"),
        {
            "company": str(company.pk),
            "name": "FY2027",
            "start_date": "2027-01-01",
            "end_date": "2027-12-31",
            "status": "OPEN",
        },
    )
    assert resp.status_code == 302
    assert FiscalYear.objects.filter(company=company, name="FY2027").exists()


# ---------------------------------------------------------------------------
# UI surfacing: buttons follow the role; the shell names it
# ---------------------------------------------------------------------------


def test_action_buttons_hidden_for_viewer_shown_for_owner(client):
    w = build_world()
    entry = _draft_entry(w)
    post_url = reverse("journal_post", args=[entry.pk])

    viewer = _user_with_role(w.company, "VIEWER", "btn-viewer")
    client.force_login(viewer)
    detail = client.get(reverse("journal_detail", args=[entry.pk]))
    assert detail.status_code == 200
    assert post_url not in detail.content.decode()
    listing = client.get(reverse("sales_invoice_list"))
    assert reverse("sales_invoice_create") not in listing.content.decode()
    year_page = client.get(reverse("fiscal_year_detail", args=[w.company.fiscal_years.get().pk]))
    assert reverse("fiscal_period_close", args=[w.company.fiscal_periods.get().pk]) not in (
        year_page.content.decode()
    )

    owner = _user_with_role(w.company, "OWNER", "btn-owner")
    client.force_login(owner)
    detail = client.get(reverse("journal_detail", args=[entry.pk]))
    assert post_url in detail.content.decode()
    listing = client.get(reverse("sales_invoice_list"))
    assert reverse("sales_invoice_create") in listing.content.decode()


def test_edit_links_hidden_for_viewer_product_list_and_party_detail(client):
    """Sprint 27 VIEWER audit: the crawl found two visible-but-dead
    controls Sprint 25's pass missed — the per-row product edit link
    (cross-company list, so the check is per product's company) and
    the party detail edit button. Both now hide for a VIEWER."""
    from apps.catalog.models import Product

    w = build_world()
    product = Product.objects.filter(company=w.company).first()
    party = Party.objects.filter(company=w.company).first()
    edit_url = reverse("product_edit", args=[product.pk])
    party_edit_url = reverse("party_edit", args=[party.pk])

    viewer = _user_with_role(w.company, "VIEWER", "audit-viewer")
    client.force_login(viewer)
    assert edit_url not in client.get(reverse("product_list")).content.decode()
    party_page = client.get(reverse("party_detail", args=[party.pk]))
    assert party_page.status_code == 200
    assert party_edit_url not in party_page.content.decode()
    # The server gate behind the (previously visible) links is unchanged.
    assert client.get(edit_url).status_code == 403
    assert client.get(party_edit_url).status_code == 403

    owner = _user_with_role(w.company, "OWNER", "audit-owner")
    client.force_login(owner)
    assert edit_url in client.get(reverse("product_list")).content.decode()
    assert party_edit_url in client.get(reverse("party_detail", args=[party.pk])).content.decode()


def test_shell_shows_company_and_role_label(client):
    w = build_world()
    owner = _user_with_role(w.company, "OWNER", "shell-owner")
    client.force_login(owner)
    content = client.get(reverse("dashboard")).content.decode()
    assert w.company.name in content
    assert "مالک" in content  # OWNER's Persian choice label

    lonely = User.objects.create_user(username="lonely", password="x")
    client.force_login(lonely)
    content = client.get(reverse("dashboard")).content.decode()
    assert "کاربر سیستم" in content  # fallback label when no membership exists
