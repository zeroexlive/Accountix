from django.urls import path

from apps.purchases import views

urlpatterns = [
    path("invoices/", views.purchase_invoice_list, name="purchase_invoice_list"),
    path("invoices/<uuid:pk>/", views.purchase_invoice_detail, name="purchase_invoice_detail"),
    path("invoices/<uuid:pk>/print/", views.purchase_invoice_print, name="purchase_invoice_print"),
    path("statement/print/", views.supplier_statement_print, name="supplier_statement_print"),
    path("payables/", views.accounts_payable_view, name="accounts_payable"),
]
