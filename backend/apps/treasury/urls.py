from django.urls import path

from apps.treasury import views

urlpatterns = [
    path("accounts/", views.treasury_account_list, name="treasury_account_list"),
    path("payments/", views.payment_list, name="payment_list"),
    path("cheques/", views.cheque_list, name="cheque_list"),
    path("open-items/", views.open_items_view, name="treasury_open_items"),
]
