from django.urls import path

from apps.accounting import views

urlpatterns = [
    path("accounts/", views.account_list, name="account_list"),
    path("accounts/new/", views.account_create, name="account_create"),
    path("journal/", views.journal_list, name="journal_list"),
    path("trial-balance/", views.trial_balance_view, name="trial_balance"),
]
