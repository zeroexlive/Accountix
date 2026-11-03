"""Sprint 20 — i18n sweep: English-mode crawl over the whole UI (ADR-046).

Sprint 19 translated the chrome; Sprint 20 wrapped every remaining
business template plus form labels, view messages and the service
errors that render verbatim into pages. This module proves it in
English mode: with the language cookie set to ``en``, a representative
list / detail / form page of every major app renders its UI labels in
English (and the Persian originals are absent), a service form error
renders in English, and success/info flashes render in English.

Seeded data names are English (``build_world``), so any Persian in a
response can only come from unwrapped UI text — that is what the
absence assertions check. Print templates are excluded by ADR-045 and
are not crawled.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from apps.accounting import services as accounting_services
from apps.inventory import services as inventory_services
from apps.organizations.models import CompanyMembership, FiscalYear
from apps.purchases import services as purchase_services
from apps.sales import services as sales_services
from apps.treasury import cheque_books, reconciliation
from apps.treasury import services as treasury_services
from apps.treasury.tests._helpers import DAY, D, build_world

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module", autouse=True)
def compiled_catalogs():
    call_command("compilemessages", verbosity=0)


@pytest.fixture(autouse=True)
def reset_active_language():
    """The set_language view activates the chosen language on this
    thread; without a reset it would leak into later tests in the
    same process (e.g. the jalali filter tests, which render under
    the default language)."""
    yield
    from django.utils import translation

    translation.deactivate_all()


@pytest.fixture
def world(db):
    w = build_world()
    w.user = User.objects.create_user(username="boss", password="<redacted>")
    CompanyMembership.objects.create(user=w.user, company=w.company, role="OWNER")
    w.purchase = purchase_services.create_purchase_invoice(
        company=w.company,
        supplier=w.supplier,
        invoice_number="PINV-1",
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[{"product": w.product, "quantity": D("10"), "unit_cost": D("100")}],
    )
    w.sale = sales_services.create_sales_invoice(
        company=w.company,
        customer=w.customer,
        invoice_number="SINV-1",
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[{"product": w.product, "quantity": D("2"), "unit_price": D("250")}],
    )
    w.payment = treasury_services.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("500"),
        payment_date=DAY,
        method="BANK_TRANSFER",
    )
    w.book = cheque_books.create_cheque_book(
        company=w.company,
        treasury_account=w.bank_treasury,
        first_number="1001",
        leaf_count=25,
    )
    w.statement = reconciliation.create_statement(
        company=w.company,
        treasury_account=w.bank_treasury,
        start_date=DAY,
        end_date=DAY,
        opening_balance=D("0"),
        closing_balance=D("0"),
    )
    w.entry = accounting_services.create_journal_draft(
        company=w.company,
        entry_date=DAY,
        description="Crawl entry",
        lines=[
            {"account": w.cash, "debit": D("100"), "credit": D("0")},
            {"account": w.revenue, "debit": D("0"), "credit": D("100")},
        ],
    )
    w.stock_doc = inventory_services.create_stock_document(
        company=w.company,
        doc_type="RECEIPT",
        warehouse=w.warehouse,
        doc_date=DAY,
        lines=[{"product": w.product, "quantity": D("5"), "unit_cost": D("100")}],
    )
    w.fiscal_year = FiscalYear.objects.get(company=w.company)
    return w


@pytest.fixture
def en_client(client, world):
    client.force_login(world.user)
    client.post(reverse("set_language"), {"language": "en", "next": "/"})
    return client


def _assert_page(client, url, present, absent, **kwargs):
    resp = client.get(url, **kwargs)
    assert resp.status_code == 200, url
    content = resp.content.decode()
    assert '<html lang="en" dir="ltr">' in content
    for text in present:
        assert text in content, (url, text)
    for text in absent:
        assert text not in content, (url, text)
    return content


def test_crawl_accounting(en_client, world):
    _assert_page(en_client, reverse("journal_list"), ["Debit", "Credit"], ["بدهکار", "بستانکار"])
    _assert_page(
        en_client,
        reverse("trial_balance"),
        ["Debit"],
        ["بدهکار"],
        data={"company": world.company.pk},
    )
    _assert_page(en_client, reverse("journal_create"), ["Document date"], ["تاریخ سند"])
    _assert_page(
        en_client,
        reverse("journal_detail", args=[world.entry.pk]),
        ["Debit"],
        ["بدهکار"],
    )
    _assert_page(en_client, reverse("opening_balance_create"), ["Credit"], ["بستانکار"])


def test_crawl_organizations(en_client, world):
    _assert_page(en_client, reverse("company_list"), ["New company"], ["شرکت جدید"])
    _assert_page(en_client, reverse("fiscal_year_list"), ["New fiscal year"], ["سال مالی جدید"])
    _assert_page(
        en_client,
        reverse("fiscal_year_detail", args=[world.fiscal_year.pk]),
        ["Close period"],
        ["بستن دوره"],
    )


def test_crawl_parties(en_client, world):
    _assert_page(en_client, reverse("party_list"), ["New party"], ["طرف‌حساب جدید"])
    _assert_page(
        en_client,
        reverse("party_detail", args=[world.supplier.pk]),
        ["Party SUP-1 — Supplier Co", "Back to list"],
        ["بازگشت به فهرست"],
    )
    _assert_page(
        en_client,
        reverse("party_create"),
        ["New party", "Save party"],
        ["طرف‌حساب جدید", "ذخیره طرف‌حساب"],
    )


def test_crawl_inventory(en_client, world):
    _assert_page(en_client, reverse("product_list"), ["New product"], ["کالای جدید"])
    _assert_page(
        en_client,
        reverse("stock_documents"),
        ["New stock document"],
        ["سند انبار جدید"],
    )
    _assert_page(
        en_client,
        reverse("stock_document_detail", args=[world.stock_doc.pk]),
        ["Company:"],
        ["شرکت:"],
    )
    _assert_page(en_client, reverse("stock_document_create"), ["Document date"], ["تاریخ سند"])


def test_crawl_purchases(en_client, world):
    _assert_page(
        en_client,
        reverse("purchase_invoice_list"),
        ["New purchase invoice"],
        ["فاکتور خرید جدید"],
    )
    _assert_page(
        en_client,
        reverse("purchase_invoice_detail", args=[world.purchase.pk]),
        ["Quantity"],
        ["مقدار"],
    )
    _assert_page(
        en_client,
        reverse("accounts_payable"),
        ["Supplier", "Payables account"],
        ["تأمین‌کننده", "حساب پرداختنی"],
        data={"company": world.company.pk, "account": world.ap.pk},
    )


def test_crawl_sales(en_client, world):
    _assert_page(
        en_client,
        reverse("sales_invoice_list"),
        ["Filter", "Search customer"],
        ["پالایش", "جستجوی مشتری"],
    )
    _assert_page(en_client, reverse("sales_invoice_create"), ["Customer"], ["مشتری:"])
    _assert_page(
        en_client,
        reverse("customer_statement"),
        ["Invoice number"],
        ["شماره فاکتور"],
        data={
            "company": world.company.pk,
            "account": world.ar.pk,
            "customer": world.customer.pk,
        },
    )


def test_crawl_treasury(en_client, world):
    _assert_page(en_client, reverse("payment_list"), ["Direction"], ["جهت"])
    _assert_page(en_client, reverse("payment_create"), ["Reference number"], ["شماره ارجاع"])
    _assert_page(
        en_client,
        reverse("payment_detail", args=[world.payment.pk]),
        ["Party"],
        ["طرف‌حساب:"],
    )
    _assert_page(en_client, reverse("cheque_book_list"), ["Bank account"], ["حساب بانکی"])
    _assert_page(
        en_client,
        reverse("bank_statement_list"),
        ["Bank account"],
        ["حساب بانکی"],
    )
    _assert_page(
        en_client,
        reverse("bank_statement_detail", args=[world.statement.pk]),
        ["Reconciliation difference", "Statement lines"],
        ["اختلاف تطبیق", "ردیف‌های صورت‌حساب"],
    )
    _assert_page(en_client, reverse("cheque_list"), ["Direction"], ["جهت"])


def test_form_error_renders_in_english(en_client, world):
    payload = {
        "company": str(world.company.pk),
        "entry_date": DAY.isoformat(),
        "description": "Unbalanced",
        "idempotency_key": "",
        "lines-TOTAL_FORMS": "2",
        "lines-INITIAL_FORMS": "0",
        "lines-MIN_NUM_FORMS": "0",
        "lines-MAX_NUM_FORMS": "1000",
        "lines-0-account": str(world.cash.pk),
        "lines-0-debit": "100",
        "lines-0-credit": "0",
        "lines-0-description": "",
        "lines-0-party": "",
        "lines-1-account": str(world.revenue.pk),
        "lines-1-debit": "0",
        "lines-1-credit": "50",
        "lines-1-description": "",
        "lines-1-party": "",
    }
    resp = en_client.post(reverse("journal_create"), payload)
    assert resp.status_code == 200
    content = resp.content.decode()
    # The wrapped service ValidationError (ADR-046) renders in English.
    assert "Journal entry is not balanced: debit 100 != credit 50." in content


def test_success_and_info_flashes_render_in_english(en_client, world):
    # Success flash: creating a party shows the wrapped view message.
    resp = en_client.post(
        reverse("party_create"),
        {
            "company": str(world.company.pk),
            "kind": "CUSTOMER",
            "code": "CUS-9",
            "name": "Flash Co",
            "legal_name": "",
            "tax_id": "",
            "registration_number": "",
            "email": "",
            "phone": "",
            "is_active": "on",
            "contacts-TOTAL_FORMS": "0",
            "contacts-INITIAL_FORMS": "0",
            "contacts-MIN_NUM_FORMS": "0",
            "contacts-MAX_NUM_FORMS": "1000",
            "addresses-TOTAL_FORMS": "0",
            "addresses-INITIAL_FORMS": "0",
            "addresses-MIN_NUM_FORMS": "0",
            "addresses-MAX_NUM_FORMS": "1000",
        },
    )
    assert resp.status_code == 302
    resp = en_client.get(resp.url)
    assert "The party was saved." in resp.content.decode()
    assert "طرف‌حساب ذخیره شد." not in resp.content.decode()

    # Info flash: closing an already-closed period.
    from apps.accounting.models import Account

    retained = Account.objects.create(
        company=world.company,
        code="3100",
        name="Retained earnings",
        account_type="EQUITY",
        normal_balance="CREDIT",
        is_postable=True,
        is_active=True,
    )
    period = world.fiscal_year.periods.get()
    resp = en_client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(retained.pk)},
    )
    assert resp.status_code == 302
    resp = en_client.post(
        reverse("fiscal_period_close", args=[period.pk]),
        {"retained_earnings": str(retained.pk)},
    )
    assert resp.status_code == 302
    resp = en_client.get(resp.url)
    content = resp.content.decode()
    assert "This period has already been closed." in content
    assert "این دوره قبلاً بسته شده است." not in content
