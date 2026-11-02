"""Shared builders for treasury tests (not a test module)."""

from datetime import date
from decimal import Decimal

from apps.accounting.models import Account
from apps.catalog.models import Product, Unit
from apps.inventory.models import Warehouse
from apps.organizations.models import Company, FiscalPeriod, FiscalYear
from apps.parties.models import Party
from apps.purchases import services as purchase_services
from apps.sales import services as sales_services
from apps.treasury import services as treasury_services

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


class World:
    pass


def build_world(*, period_status="OPEN", company_name="Treasury Trading Co"):
    w = World()
    w.company = Company.objects.create(name=company_name)
    fy = FiscalYear.objects.create(
        company=w.company,
        name="FY2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
    )
    FiscalPeriod.objects.create(
        company=w.company,
        fiscal_year=fy,
        name="2026",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        status=period_status,
    )
    c = w.company
    w.cash = _acct(c, "1100", "Cash", "ASSET", "DEBIT")
    w.bank = _acct(c, "1110", "Bank", "ASSET", "DEBIT")
    w.cheques_in_hand = _acct(c, "1150", "Cheques in hand", "ASSET", "DEBIT")
    w.ar = _acct(c, "1200", "Accounts receivable", "ASSET", "DEBIT")
    w.inventory = _acct(c, "1300", "Inventory", "ASSET", "DEBIT")
    w.tax_in = _acct(c, "1350", "Input VAT", "ASSET", "DEBIT")
    w.ap = _acct(c, "2100", "Accounts payable", "LIABILITY", "CREDIT")
    w.cheques_payable = _acct(c, "2150", "Cheques payable", "LIABILITY", "CREDIT")
    w.tax_out = _acct(c, "2200", "Output VAT payable", "LIABILITY", "CREDIT")
    w.revenue = _acct(c, "4100", "Sales revenue", "REVENUE", "CREDIT")
    w.cogs = _acct(c, "5100", "Cost of goods sold", "EXPENSE", "DEBIT")
    w.expense = _acct(c, "6100", "Operating expense", "EXPENSE", "DEBIT")

    w.supplier = Party.objects.create(company=c, code="SUP-1", name="Supplier Co", kind="SUPPLIER")
    w.customer = Party.objects.create(company=c, code="CUS-1", name="Customer Co", kind="CUSTOMER")
    w.customer2 = Party.objects.create(company=c, code="CUS-2", name="Other Co", kind="CUSTOMER")
    pcs = Unit.objects.create(company=c, code="PCS", name="Piece")
    w.product = Product.objects.create(company=c, sku="P-1", name="Widget", base_unit=pcs)
    w.warehouse = Warehouse.objects.create(company=c, code="WH1", name="Main warehouse")

    w.cash_treasury = treasury_services.create_treasury_account(
        company=c, kind="CASH", name="Main cash", gl_account=w.cash
    )
    w.bank_treasury = treasury_services.create_treasury_account(
        company=c, kind="BANK", name="Main bank", gl_account=w.bank, bank_name="Melli"
    )
    return w


def post_purchase(w, number="PINV-1"):
    purchase = purchase_services.create_purchase_invoice(
        company=w.company,
        supplier=w.supplier,
        invoice_number=number,
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[
            {"product": w.product, "quantity": D("10"), "unit_cost": D("100"), "tax_rate": D("0.1")}
        ],
    )
    return purchase_services.post_purchase_invoice(
        purchase,
        gl_accounts={
            "inventory": w.inventory,
            "payables": w.ap,
            "tax": w.tax_in,
            "expense": w.expense,
        },
    )


def post_sale(w, number="SINV-1"):
    sale = sales_services.create_sales_invoice(
        company=w.company,
        customer=w.customer,
        invoice_number=number,
        invoice_date=DAY,
        warehouse=w.warehouse,
        lines=[
            {"product": w.product, "quantity": D("4"), "unit_price": D("250"), "tax_rate": D("0.1")}
        ],
    )
    return sales_services.post_sales_invoice(
        sale,
        gl_accounts={
            "receivables": w.ar,
            "revenue": w.revenue,
            "tax_payable": w.tax_out,
            "cogs": w.cogs,
            "inventory": w.inventory,
        },
    )
