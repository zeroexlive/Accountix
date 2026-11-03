"""Sprint 30 (ADR-055) — the permanent fa-leak regression crawl.

Jason's bug report: English sentences appeared inside Persian
pages. This module crawls EVERY app page in fa mode as an OWNER
over a fully populated world whose user data is Persian (so data
never pollutes the audit), harvests visible text plus user-facing
attributes (placeholder/title/aria-label/alt, submit values), and
fails on:

* SENTENCE rule — a run of >= 2 consecutive Latin words with >= 5
  letters total (catches real sentences and two-word labels like
  "Accounts payable"), minus SENTENCE_ALLOWLIST;
* STRICT-ZONE rule — inside chrome elements that must always be
  product language (label/th/button/option/legend/h1-h3), ANY
  Latin token of >= 3 letters is flagged (catches one-word labels
  like "Status"), minus STRICT_TOKEN_ALLOWLIST;
* POST flows that re-render forms with errors (framework strings
  included — class (3) of the ADR-055 census: Django's bundled fa
  translations cover them, proven here continuously).

The allowlists below are the whole exception surface; each entry
carries its justification. If a future change needs a new entry,
the ADR expects the justification to be written here, in the open.
"""

import re
from datetime import date
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.urls import reverse

from apps.accounting import services as accounting_services
from apps.inventory import services as inventory_services
from apps.organizations.models import CompanyMembership, FiscalYear
from apps.treasury import cheque_books, reconciliation
from apps.treasury import services as treasury_services
from apps.treasury.tests._helpers import DAY, D, build_world, post_purchase, post_sale

User = get_user_model()
pytestmark = pytest.mark.django_db


@pytest.fixture(scope="module", autouse=True)
def compiled_catalogs():
    call_command("compilemessages", verbosity=0)


ACCOUNT_NAMES = {
    "1100": "نقد",
    "1110": "بانک",
    "1150": "چک‌های دریافتی",
    "1200": "حساب‌های دریافتنی",
    "1300": "موجودی کالا",
    "1350": "مالیات خرید",
    "2100": "حساب‌های پرداختنی",
    "2150": "چک‌های پرداختنی",
    "2200": "مالیات فروش",
    "4100": "درآمد فروش",
    "5100": "بهای تمام‌شده",
    "6100": "هزینه‌های عملیاتی",
}


@pytest.fixture
def world(db):
    # The world's stored descriptions must be created under fa:
    # pin the active language for the fixture's service calls (a
    # previous test's en-mode request can leave 'en' active in the
    # test thread — language state is not reset between tests).
    from django.utils import translation

    translation.activate("fa")
    w = build_world(company_name="شرکت بازرگانی نمونه")
    # Persian fixture data: user-owned strings must not pollute the audit.
    from apps.accounting.models import Account

    for acct in Account.objects.filter(company=w.company):
        acct.name = ACCOUNT_NAMES[acct.code]
        acct.save()
    fy = FiscalYear.objects.get(company=w.company)
    fy.name = "سال مالی ۱۴۰۵"
    fy.save()
    w.supplier.name = "تأمین‌کننده نمونه"
    w.supplier.save()
    w.customer.name = "مشتری نمونه"
    w.customer.save()
    w.customer2.name = "مشتری دوم"
    w.customer2.save()
    w.product.name = "کالای نمونه"
    w.product.min_stock_level = D("10")
    w.product.save()
    w.warehouse.name = "انبار مرکزی"
    w.warehouse.save()
    unit = w.product.base_unit
    unit.name = "عدد"
    unit.save()
    w.cash_treasury.name = "صندوق اصلی"
    w.cash_treasury.save()
    w.bank_treasury.name = "بانک اصلی"
    w.bank_treasury.bank_name = "ملی"
    w.bank_treasury.save()
    w.fiscal_year = fy

    w.user = User.objects.create_user(
        username="boss", password="Str0ng!Pass1", first_name="مدیر", last_name="نمونه"
    )
    CompanyMembership.objects.create(user=w.user, company=w.company, role="OWNER")
    w.member = User.objects.create_user(
        username="accountant", password="Str0ng!Pass1", first_name="رضا", last_name="کریمی"
    )
    CompanyMembership.objects.create(user=w.member, company=w.company, role="ACCOUNTANT")

    w.purchase = post_purchase(w)
    w.sale = post_sale(w)
    w.payment = treasury_services.create_payment(
        company=w.company,
        direction="RECEIPT",
        party=w.customer,
        treasury_account=w.bank_treasury,
        amount=D("1100"),
        payment_date=DAY,
        method="BANK_TRANSFER",
    )
    w.payment = treasury_services.post_payment(
        w.payment, gl_accounts={"receivable": w.ar, "bank": w.bank}
    )
    treasury_services.allocate_payment(w.payment, w.sale, D("1100"))

    def cheque_receipt(amount, number):
        p = treasury_services.create_payment(
            company=w.company,
            direction="RECEIPT",
            party=w.customer,
            treasury_account=w.bank_treasury,
            amount=D(amount),
            payment_date=DAY,
            method="CHEQUE",
            cheque={
                "bank_name": "ملی",
                "cheque_number": number,
                "due_date": date(2026, 6, 15),
                "sayad_id": "SY-123",
            },
        )
        p = treasury_services.post_payment(
            p, gl_accounts={"receivable": w.ar, "cheques_in_hand": w.cheques_in_hand}
        )
        return p.cheques.first()

    ch1 = cheque_receipt("300", "CHQ-1")
    treasury_services.deposit_cheque(ch1)
    treasury_services.clear_cheque(ch1, bank_treasury_account=w.bank_treasury)
    w.cheque = cheque_receipt("200", "CHQ-2")  # stays in hand
    ch3 = cheque_receipt("150", "CHQ-3")
    treasury_services.bounce_cheque(ch3)

    from apps.purchases import services as purchase_services
    from apps.sales import services as sales_services

    sale_line = w.sale.lines.first()
    w.sale_return = sales_services.create_sales_return(
        company=w.company,
        original_invoice=w.sale,
        return_number="SRET-1",
        return_date=DAY,
        lines=[{"invoice_line": sale_line, "quantity": D("1")}],
    )
    purchase_line = w.purchase.lines.first()
    w.purchase_return = purchase_services.create_purchase_return(
        company=w.company,
        original_invoice=w.purchase,
        return_number="PRET-1",
        return_date=DAY,
        lines=[{"invoice_line": purchase_line, "quantity": D("1")}],
    )
    w.count = inventory_services.create_inventory_count(
        company=w.company,
        warehouse=w.warehouse,
        count_date=DAY,
        lines=[{"product": w.product, "counted_qty": D("9")}],
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
        closing_balance=D("1100"),
    )
    reconciliation.add_statement_line(
        w.statement, line_date=DAY, amount=D("1100"), description="واریز نمونه", reference="REF-1"
    )
    reconciliation.add_statement_line(
        w.statement, line_date=DAY, amount=D("-50"), description="کارمزد بانک", reference="REF-2"
    )
    w.entry = accounting_services.create_journal_draft(
        company=w.company,
        entry_date=DAY,
        description="سند نمونه",
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
    return w


SENTENCE_RE = re.compile(r"[A-Za-z][A-Za-z'’-]*(?:[ \t]+[A-Za-z][A-Za-z'’-]*){1,}")
ATTRS = ("placeholder", "title", "aria-label", "alt")


class TextHarvest(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "svg"):
            self.skip += 1
        d = dict(attrs)
        for key in ATTRS:
            if d.get(key):
                self.chunks.append(d[key])
        if tag == "input" and d.get("type") in ("submit", "button", "reset") and d.get("value"):
            self.chunks.append(d["value"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def latin_sentences(html):
    parser = TextHarvest()
    parser.feed(html)
    hits = set()
    for chunk in parser.chunks:
        text = " ".join(chunk.split())
        for m in SENTENCE_RE.finditer(text):
            s = m.group(0).strip(" -'’")
            if sum(c.isalpha() for c in s) >= 5:
                hits.add(s)
    return hits


def page_urls(w):
    c = w.company
    return [
        ("dashboard", reverse("dashboard")),
        ("account_list", reverse("account_list")),
        ("account_create", reverse("account_create")),
        ("journal_list", reverse("journal_list")),
        ("journal_create", reverse("journal_create")),
        ("journal_detail", reverse("journal_detail", args=[w.entry.pk])),
        ("opening_balance_create", reverse("opening_balance_create")),
        ("trial_balance", reverse("trial_balance") + f"?company={c.pk}"),
        ("income_statement", reverse("income_statement") + f"?company={c.pk}"),
        ("balance_sheet", reverse("balance_sheet") + f"?company={c.pk}"),
        ("company_list", reverse("company_list")),
        ("company_create", reverse("company_create")),
        ("company_detail", reverse("company_detail", args=[c.pk])),
        ("company_members", reverse("company_members", args=[c.pk])),
        ("fiscal_year_list", reverse("fiscal_year_list")),
        ("fiscal_year_create", reverse("fiscal_year_create")),
        ("fiscal_year_detail", reverse("fiscal_year_detail", args=[w.fiscal_year.pk])),
        ("party_list", reverse("party_list")),
        ("party_create", reverse("party_create")),
        ("party_detail", reverse("party_detail", args=[w.supplier.pk])),
        ("party_edit", reverse("party_edit", args=[w.supplier.pk])),
        ("product_list", reverse("product_list")),
        ("product_create", reverse("product_create")),
        ("product_edit", reverse("product_edit", args=[w.product.pk])),
        ("unit_create", reverse("unit_create")),
        ("category_create", reverse("category_create")),
        ("warehouse_create", reverse("warehouse_create")),
        ("stock_balances", reverse("stock_balances") + f"?company={c.pk}"),
        ("stock_movements", reverse("stock_movements") + f"?company={c.pk}"),
        ("inventory_counts", reverse("inventory_counts")),
        ("inventory_count_create", reverse("inventory_count_create")),
        ("stock_documents", reverse("stock_documents")),
        ("stock_document_create", reverse("stock_document_create")),
        ("stock_document_detail", reverse("stock_document_detail", args=[w.stock_doc.pk])),
        ("purchase_invoice_list", reverse("purchase_invoice_list")),
        ("purchase_invoice_create", reverse("purchase_invoice_create")),
        ("purchase_invoice_detail", reverse("purchase_invoice_detail", args=[w.purchase.pk])),
        ("purchase_return_create", reverse("purchase_return_create", args=[w.purchase.pk])),
        (
            "accounts_payable",
            reverse("accounts_payable") + f"?company={c.pk}&account={w.ap.pk}",
        ),
        ("sales_invoice_list", reverse("sales_invoice_list")),
        ("sales_invoice_create", reverse("sales_invoice_create")),
        ("sales_invoice_detail", reverse("sales_invoice_detail", args=[w.sale.pk])),
        ("sales_return_create", reverse("sales_return_create", args=[w.sale.pk])),
        (
            "accounts_receivable",
            reverse("accounts_receivable") + f"?company={c.pk}&account={w.ar.pk}",
        ),
        (
            "customer_statement",
            reverse("customer_statement")
            + f"?company={c.pk}&account={w.ar.pk}&customer={w.customer.pk}",
        ),
        ("treasury_account_list", reverse("treasury_account_list")),
        ("treasury_account_create", reverse("treasury_account_create")),
        ("payment_list", reverse("payment_list")),
        ("payment_create", reverse("payment_create")),
        ("payment_detail", reverse("payment_detail", args=[w.payment.pk])),
        ("cheque_list", reverse("cheque_list")),
        ("cheque_detail", reverse("cheque_detail", args=[w.cheque.pk])),
        ("sales_return_detail", reverse("sales_return_detail", args=[w.sale_return.pk])),
        (
            "purchase_return_detail",
            reverse("purchase_return_detail", args=[w.purchase_return.pk]),
        ),
        ("inventory_count_detail", reverse("inventory_count_detail", args=[w.count.pk])),
        ("treasury_open_items", reverse("treasury_open_items") + f"?company={c.pk}"),
        ("bank_statement_list", reverse("bank_statement_list")),
        ("bank_statement_create", reverse("bank_statement_create")),
        ("bank_statement_detail", reverse("bank_statement_detail", args=[w.statement.pk])),
        ("cheque_book_list", reverse("cheque_book_list")),
        ("cheque_book_create", reverse("cheque_book_create")),
        ("cheque_book_detail", reverse("cheque_book_detail", args=[w.book.pk])),
        ("profile", reverse("profile")),
        ("password_change", reverse("password_change")),
    ]




# --- Allowlists: the entire exception surface (ADR-055) ----------

SENTENCE_ALLOWLIST = (
    # The shell footer's build attribution is a proper name, kept
    # in Latin by design: "developed with Muse Spark".
    "Muse Spark",
)

STRICT_TOKEN_ALLOWLIST = {
    # File-format labels ARE the product vocabulary; banks and
    # accountants name these formats in Latin everywhere.
    "CSV",
    "CAMT.053",
    "OFX",
    "XLSX",
    "PDF",
    # The income-statement filter label pairs the Persian term with
    # the universal accounting acronym: «حساب‌های بهای تمام‌شده (COGS)».
    "COGS",
    # Same deliberate pattern for the product code: «کد کالا (SKU)».
    "SKU",
    # The language switcher names the other language in its own
    # script — deliberate, standard practice.
    "English",
    # The brand mark.
    "Accountix",
}

STRICT_TAGS = {"label", "th", "button", "option", "legend", "h1", "h2", "h3"}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9._-]*")


class StrictHarvest(HTMLParser):
    """Collects text that lives inside chrome elements which must
    always render in the product language."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in STRICT_TAGS:
            self.depth += 1

    def handle_endtag(self, tag):
        if tag in STRICT_TAGS and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.depth:
            self.chunks.append(data)


def sentence_violations(html):
    hits = latin_sentences(html)
    return {
        h
        for h in hits
        if not any(allowed in h for allowed in SENTENCE_ALLOWLIST)
    }


def world_data_tokens(w):
    """Latin identifiers that are the WORLD'S OWN DATA (unit codes
    like PCS): data is exempt from the chrome rules — a user may
    name their units and codes in any script."""
    from apps.catalog.models import Unit

    return set(Unit.objects.filter(company=w.company).values_list("code", flat=True))


def strict_violations(html, data_tokens=frozenset()):
    parser = StrictHarvest()
    parser.feed(html)
    bad = set()
    for chunk in parser.chunks:
        for token in TOKEN_RE.findall(chunk):
            alpha = [c for c in token if c.isalpha()]
            # Tokens carrying a digit are user-data identifiers
            # (invoice/cheque/party/product codes like SINV-1 or
            # CHQ-2): data, in whatever script the user typed it.
            # Pure-alpha tokens are product vocabulary and must be
            # translated.
            if (
                len(alpha) >= 3
                and not any(c.isdigit() for c in token)
                and token not in STRICT_TOKEN_ALLOWLIST
                and token not in data_tokens
            ):
                bad.add(token)
    return bad


def page_violations(html, data_tokens=frozenset()):
    out = {f"sentence: {h}" for h in sentence_violations(html)}
    out |= {f"strict-zone token: {t}" for t in strict_violations(html, data_tokens)}
    return out


# --- The crawl ----------------------------------------------------


def test_fa_crawl_get_pages_are_latin_free(client, world):
    client.force_login(world.user)
    data_tokens = world_data_tokens(world)
    failures = {}
    for name, url in page_urls(world):
        resp = client.get(url)
        if resp.status_code != 200:
            failures[name] = {f"<HTTP {resp.status_code}>"}
            continue
        violations = page_violations(resp.content.decode(), data_tokens)
        if violations:
            failures[name] = violations
    assert failures == {}


def test_fa_crawl_post_error_pages_are_latin_free(client, world):
    from django.core.files.uploadedfile import SimpleUploadedFile

    w = world
    data_tokens = world_data_tokens(w)
    failures = {}

    def check(name, resp):
        violations = page_violations(resp.content.decode(), data_tokens)
        if violations:
            failures[name] = violations

    # Anonymous: failed login -> Django auth form error (framework
    # string, class (3): served by Django's bundled fa catalog).
    client.logout()
    resp = client.post(
        reverse("login"), {"username": "boss", "password": "wrong-pass"}, follow=True
    )
    check("login_bad", resp)

    client.force_login(w.user)
    resp = client.post(
        reverse("password_change"),
        {"old_password": "not-the-password", "new_password1": "123", "new_password2": "456"},
        follow=True,
    )
    check("password_change_err", resp)
    resp = client.post(
        reverse("password_change"),
        {
            "old_password": "Str0ng!Pass1",
            "new_password1": "password",
            "new_password2": "password",
        },
        follow=True,
    )
    check("password_change_weak", resp)
    resp = client.post(
        reverse("profile"),
        {"first_name": "مدیر", "last_name": "نمونه", "email": "not-an-email"},
        follow=True,
    )
    check("profile_err", resp)
    resp = client.post(
        reverse("company_member_add_new", args=[w.company.pk]),
        {
            "username": "newbie",
            "first_name": "",
            "last_name": "",
            "password1": "123",
            "password2": "1234",
            "role": "VIEWER",
        },
        follow=True,
    )
    check("member_add_new_err", resp)
    resp = client.post(
        reverse("journal_create"),
        {
            "company": str(w.company.pk),
            "entry_date": DAY.isoformat(),
            "description": "سند نامتوازن",
            "idempotency_key": "",
            "lines-TOTAL_FORMS": "2",
            "lines-INITIAL_FORMS": "0",
            "lines-MIN_NUM_FORMS": "0",
            "lines-MAX_NUM_FORMS": "1000",
            "lines-0-account": str(w.cash.pk),
            "lines-0-debit": "100",
            "lines-0-credit": "0",
            "lines-0-party": "",
            "lines-0-description": "",
            "lines-1-account": str(w.revenue.pk),
            "lines-1-debit": "0",
            "lines-1-credit": "50",
            "lines-1-party": "",
            "lines-1-description": "",
        },
        follow=True,
    )
    check("journal_create_err", resp)
    resp = client.post(reverse("purchase_invoice_create"), {}, follow=True)
    check("purchase_create_empty", resp)
    resp = client.post(
        reverse("bank_statement_import", args=[w.statement.pk]),
        {"file": SimpleUploadedFile("s.csv", b"garbage,content\n1,2\n", content_type="text/csv")},
        follow=True,
    )
    check("statement_import_garbage", resp)
    resp = client.post(reverse("account_create"), {}, follow=True)
    check("account_create_empty", resp)
    resp = client.post(reverse("company_create"), {}, follow=True)
    check("company_create_empty", resp)

    assert failures == {}


def test_new_records_store_descriptions_in_the_active_language(world):
    """ADR-055 class (5): stored descriptions are frozen at
    creation time IN THE CREATION LANGUAGE. History is never
    rewritten; what this pins is that records created under fa
    store Persian (and, symmetrically, under en store English)."""
    from django.utils import translation

    from apps.accounting.models import JournalEntry
    from apps.treasury.tests._helpers import post_purchase as _post_purchase
    from apps.treasury.tests._helpers import post_sale as _post_sale

    _post_purchase(world, number="PINV-STOCK")  # headroom for two more sales
    arabic = re.compile(r"[\u0600-\u06FF]")

    with translation.override("fa"):
        sale_fa = _post_sale(world, number="SINV-FA")
    descriptions_fa = set(
        JournalEntry.objects.filter(
            company=world.company, source_id=str(sale_fa.id)
        ).values_list("description", flat=True)
    )
    assert descriptions_fa, "expected journal entries for the fa sale"
    assert all(arabic.search(d) for d in descriptions_fa), descriptions_fa
    assert not any("Sales invoice" in d for d in descriptions_fa)

    with translation.override("en"):
        sale_en = _post_sale(world, number="SINV-EN")
    descriptions_en = set(
        JournalEntry.objects.filter(
            company=world.company, source_id=str(sale_en.id)
        ).values_list("description", flat=True)
    )
    assert any("Sales invoice SINV-EN" in d for d in descriptions_en), descriptions_en
