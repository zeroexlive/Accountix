from django.urls import path

from apps.purchases import views

urlpatterns = [
    path("invoices/", views.purchase_invoice_list, name="purchase_invoice_list"),
    path("invoices/<uuid:pk>/", views.purchase_invoice_detail, name="purchase_invoice_detail"),
    path("payables/", views.accounts_payable_view, name="accounts_payable"),
]
