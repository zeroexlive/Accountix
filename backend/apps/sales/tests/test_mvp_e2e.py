"""Internal MVP end-to-end test (master prompt §20.4).

One continuous, number-asserting workflow:

    company + fiscal calendar + chart of accounts
      -> supplier / customer / product / warehouse
      -> purchase invoice posted (stock in at MWAC, AP up)
      -> sales invoice posted (stock out, COGS, AR up, revenue + tax)
      -> trial balance balances; inventory valuation == GL inventory;
         AP subledger == AP account; AR subledger == AR account
      -> a customer payment recorded as a PLAIN MANUAL JOURNAL through
         the accounting service (Dr cash / Cr receivables, party-tagged)
      -> AR subledger drops to zero; trial balance still balances

The payment step is a **test-only** use of the journal service. It is
NOT a treasury feature: no Payment/PaymentAllocation records exist, and
the sales invoice's ``payment_status`` deliberately stays UNPAID —
treasury, which owns that field, is Sprint 06.
"""

from datetime import date
from decimal import Decimal

import pytest

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import Account
from apps.accounting.services import post_journal_entry
from apps.catalog.models import Product, Unit
from apps.inventory import reporting as inv_reporting
from apps.inventory.models import Warehouse
from apps.organizations.models import Company, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.purchases import reporting as purchase_reporting
from apps.purchases import services as purchase_services
from apps.sales import reporting as sales_reporting
from apps.sales import services as sales_services

D = Decimal
DAY = date(2026, 6, 1)


def _acct(company, code, name, account_type, normal_balance):
    return Account.objects.create(
        company=company,
        code=code,
        name=name,
        account_type=account_type,
        normal_balance=normal_balance,
        is_postable=True,
        is_active=True,
    )


@pytest.mark.django_db
def test_internal_mvp_purchase_to_sale_to_payment(db):
    # -- Stage 1: company, fiscal calendar, chart of accounts ---------------
    company = Company.objects.create(name="MVP Trading Co")
    fy = FiscalYear.objects.create(
        company=company, name="FY2026", start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)
    )
    FiscalPeriod.objects.create(
        company=company,
        fiscal_year=fy,
        name="2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status="OPEN",
    )
    cash = _acct(company, "1100", "Cash", "ASSET", "DEBIT")
    ar = _acct(company, "1200", "Accounts receivable", "ASSET", "DEBIT")
    inventory = _acct(company, "1300", "Inventory", "ASSET", "DEBIT")
    tax_in = _acct(company, "1350", "Input VAT", "ASSET", "DEBIT")
    ap = _acct(company, "2100", "Accounts payable", "LIABILITY", "CREDIT")
    tax_out = _acct(company, "2200", "Output VAT payable", "LIABILITY", "CREDIT")
    revenue = _acct(company, "4100", "Sales revenue", "REVENUE", "CREDIT")
    cogs = _acct(company, "5100", "Cost of goods sold", "EXPENSE", "DEBIT")
    expense = _acct(company, "6100", "Operating expense", "EXPENSE", "DEBIT")

    # -- Stage 2: parties, product, warehouse -------------------------------
    supplier = Party.objects.create(
        company=company, code="SUP-1", name="Supplier Co", kind="SUPPLIER"
    )
    customer = Party.objects.create(
        company=company, code="CUS-1", name="Customer Co", kind="CUSTOMER"
    )
    pcs = Unit.objects.create(company=company, code="PCS", name="Piece")
    product = Product.objects.create(company=company, sku="P-1", name="Widget", base_unit=pcs)
    warehouse = Warehouse.objects.create(company=company, code="WH1", name="Main warehouse")

    # -- Stage 3: purchase 10 @ 100 + 10% tax -------------------------------
    purchase = purchase_services.create_purchase_invoice(
        company=company,
        supplier=supplier,
        invoice_number="PINV-1",
        invoice_date=DAY,
        warehouse=warehouse,
        lines=[
            {
                "product": product,
                "quantity": D("10"),
                "unit_cost": D("100"),
                "tax_rate": D("0.1"),
            }
        ],
    )
    purchase = purchase_services.post_purchase_invoice(
        purchase,
        gl_accounts={"inventory": inventory, "payables": ap, "tax": tax_in, "expense": expense},
    )
    assert purchase.grand_total == D("1100")  # 1000 + 100 tax
    row = inv_reporting.stock_balance(company, warehouse, product)
    assert row["quantity"] == D("10")
    assert row["value"] == D("1000")
    assert row["average_cost"] == D("100")
    assert purchase_reporting.supplier_balance(company, ap, supplier) == D("1100")

    # -- Stage 4: sale 4 @ 250 + 10% tax ------------------------------------
    sale = sales_services.create_sales_invoice(
        company=company,
        customer=customer,
        invoice_number="SINV-1",
        invoice_date=DAY,
        warehouse=warehouse,
        lines=[
            {
                "product": product,
                "quantity": D("4"),
                "unit_price": D("250"),
                "tax_rate": D("0.1"),
            }
        ],
    )
    sale = sales_services.post_sales_invoice(
        sale,
        gl_accounts={
            "receivables": ar,
            "revenue": revenue,
            "tax_payable": tax_out,
            "cogs": cogs,
            "inventory": inventory,
        },
    )
    assert sale.grand_total == D("1100")  # 1000 + 100 tax
    assert sale.cogs_journal_entry.lines.get(account=cogs).debit == D("400")
    row = inv_reporting.stock_balance(company, warehouse, product)
    assert row["quantity"] == D("6")
    assert row["value"] == D("600")

    # -- Stage 5: reconciliations --------------------------------------------
    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]
    assert tb["total_debit"] == tb["total_credit"] == D("2600")
    # Inventory: stock ledger value == GL inventory account balance.
    assert inv_reporting.inventory_valuation(company) == D("600")
    assert acct_reporting.account_balance(company, inventory) == D("600")
    # AP subledger == AP account (credit balance shown positive by the view).
    assert purchase_reporting.ap_total(company, ap) == D("1100")
    assert acct_reporting.account_balance(company, ap) == D("-1100")
    # AR subledger == AR account.
    assert sales_reporting.customer_balance(company, ar, customer) == D("1100")
    assert sales_reporting.ar_total(company, ar) == D("1100")
    assert acct_reporting.account_balance(company, ar) == D("1100")
    # Revenue / tax / COGS landed as expected.
    assert acct_reporting.account_balance(company, revenue) == D("-1000")
    assert acct_reporting.account_balance(company, tax_out) == D("-100")
    assert acct_reporting.account_balance(company, cogs) == D("400")

    # -- Stage 6: customer payment as a plain manual journal (test-only) ----
    post_journal_entry(
        company=company,
        entry_date=DAY,
        lines=[
            {"account": cash, "debit": D("1100")},
            {"account": ar, "credit": D("1100"), "party": customer},
        ],
        description="Customer payment (manual journal — MVP test stub, not treasury)",
        source_type="MVP_TEST_PAYMENT",
        source_id=str(sale.id),
        idempotency_key=f"mvp-test-payment:{sale.id}",
    )
    assert sales_reporting.customer_balance(company, ar, customer) == D("0")
    assert acct_reporting.account_balance(company, ar) == D("0")
    assert acct_reporting.account_balance(company, cash) == D("1100")
    # The invoice's payment_status is treasury's field: the manual journal
    # must NOT have moved it.
    sale.refresh_from_db()
    assert sale.payment_status == "UNPAID"

    tb = acct_reporting.trial_balance(company)
    assert tb["is_balanced"]
    assert tb["total_debit"] == tb["total_credit"]
