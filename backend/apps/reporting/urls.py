from django.urls import path

from apps.reporting import exports

urlpatterns = [
    path("exports/trial-balance.csv", exports.trial_balance_csv, name="export_trial_balance_csv"),
    path(
        "exports/trial-balance.xlsx", exports.trial_balance_xlsx, name="export_trial_balance_xlsx"
    ),
    path(
        "exports/general-ledger.csv", exports.general_ledger_csv, name="export_general_ledger_csv"
    ),
    path(
        "exports/stock-balances.csv", exports.stock_balances_csv, name="export_stock_balances_csv"
    ),
    path(
        "exports/stock-balances.xlsx",
        exports.stock_balances_xlsx,
        name="export_stock_balances_xlsx",
    ),
    path("exports/open-items.csv", exports.open_items_csv, name="export_open_items_csv"),
]
