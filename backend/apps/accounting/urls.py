from django.urls import path

from apps.accounting import views

urlpatterns = [
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_create, name="account_create"),
    path("journal/", views.journal_list, name="journal_list"),
    path("journal/new/", views.journal_create, name="journal_create"),
    path("journal/<uuid:pk>/", views.journal_detail, name="journal_detail"),
    path("journal/<uuid:pk>/post/", views.journal_post, name="journal_post"),
    path("journal/<uuid:pk>/reverse/", views.journal_reverse, name="journal_reverse"),
    path("opening-balances/", views.opening_balance_create, name="opening_balance_create"),
    path("trial-balance/", views.trial_balance_view, name="trial_balance"),
    path("income-statement/", views.income_statement_view, name="income_statement"),
    path("balance-sheet/", views.balance_sheet_view, name="balance_sheet"),
]
