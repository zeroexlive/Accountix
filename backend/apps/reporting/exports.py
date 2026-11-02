"""File exports (Sprint 08): CSV (stdlib) and XLSX (openpyxl).

Exports are read-only presentations of the same derived reporting data
the pages show. Every endpoint resolves its company through the
requesting user's memberships — a company the user does not belong to
is a 404, exactly as on the pages — and applies the same filters
(period / warehouse / account) the corresponding page supports.
"""

import csv
import io

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from apps.accounting import reporting as acct_reporting
from apps.accounting.models import Account
from apps.core.access import user_company_ids
from apps.inventory import reporting as inv_reporting
from apps.inventory.models import Warehouse
from apps.organizations.models import Company, FiscalPeriod
from apps.treasury import reporting as treasury_reporting

XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _member_company(request):
    companies = Company.objects.filter(id__in=user_company_ids(request.user))
    return get_object_or_404(companies, pk=request.GET.get("company"))


def _member_period(request, company):
    period_id = request.GET.get("period")
    if not period_id:
        return None
    return get_object_or_404(FiscalPeriod.objects.filter(company=company), pk=period_id)


def _csv_response(filename, rows):
    buffer = io.StringIO()
    csv.writer(buffer).writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _xlsx_response(filename, sheet_title, rows):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    for row in rows:
        sheet.append(list(row))
    buffer = io.BytesIO()
    workbook.save(buffer)
    response = HttpResponse(buffer.getvalue(), content_type=XLSX_CONTENT_TYPE)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _trial_balance_rows(company, period):
    result = acct_reporting.trial_balance(company, fiscal_period=period)
    rows = [["code", "account", "debit", "credit", "balance"]]
    for row in result["rows"]:
        rows.append(
            [row["code"], row["name"], str(row["debit"]), str(row["credit"]), str(row["balance"])]
        )
    rows.append(["TOTAL", "", str(result["total_debit"]), str(result["total_credit"]), ""])
    return rows


@login_required
def trial_balance_csv(request):
    company = _member_company(request)
    rows = _trial_balance_rows(company, _member_period(request, company))
    return _csv_response("trial-balance.csv", rows)


@login_required
def trial_balance_xlsx(request):
    company = _member_company(request)
    rows = _trial_balance_rows(company, _member_period(request, company))
    # Numeric cells (not strings) so spreadsheet users can sum them.
    numeric = [rows[0]] + [
        [r[0], r[1]] + [float(v) if v != "" else None for v in r[2:]] for r in rows[1:]
    ]
    return _xlsx_response("trial-balance.xlsx", "Trial balance", numeric)


@login_required
def general_ledger_csv(request):
    company = _member_company(request)
    accounts = Account.objects.filter(company=company)
    account = get_object_or_404(accounts, pk=request.GET.get("account"))
    period = _member_period(request, company)
    rows = [["date", "description", "debit", "credit", "running_balance"]]
    for line in acct_reporting.general_ledger(company, account, fiscal_period=period):
        rows.append(
            [
                line["date"].isoformat(),
                line["description"],
                str(line["debit"]),
                str(line["credit"]),
                str(line["running_balance"]),
            ]
        )
    return _csv_response("general-ledger.csv", rows)


def _stock_balance_rows(request, company):
    warehouse = None
    warehouse_id = request.GET.get("warehouse")
    if warehouse_id:
        warehouse = get_object_or_404(Warehouse.objects.filter(company=company), pk=warehouse_id)
    rows = [["warehouse", "sku", "product", "quantity", "value", "average_cost"]]
    for row in inv_reporting.stock_balances(company, warehouse=warehouse):
        rows.append(
            [
                row["warehouse_code"],
                row["sku"],
                row["name"],
                str(row["quantity"]),
                str(row["value"]),
                str(row["average_cost"]),
            ]
        )
    return rows


@login_required
def stock_balances_csv(request):
    company = _member_company(request)
    return _csv_response("stock-balances.csv", _stock_balance_rows(request, company))


@login_required
def stock_balances_xlsx(request):
    company = _member_company(request)
    rows = _stock_balance_rows(request, company)
    numeric = [rows[0]] + [r[:3] + [float(v) for v in r[3:]] for r in rows[1:]]
    return _xlsx_response("stock-balances.xlsx", "Stock balances", numeric)


@login_required
def open_items_csv(request):
    company = _member_company(request)
    rows = [
        [
            "kind",
            "invoice_number",
            "date",
            "party_code",
            "party",
            "total",
            "allocated",
            "outstanding",
        ]
    ]
    for item in treasury_reporting.open_items(company):
        invoice = item["invoice"]
        rows.append(
            [
                item["kind"],
                invoice.invoice_number,
                invoice.invoice_date.isoformat(),
                item["party"].code,
                item["party"].name,
                str(item["total"]),
                str(item["allocated"]),
                str(item["outstanding"]),
            ]
        )
    return _csv_response("open-items.csv", rows)
