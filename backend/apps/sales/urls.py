from django.urls import path

from apps.sales import views

urlpatterns = [
    path("invoices/", views.sales_invoice_list, name="sales_invoice_list"),
    path("invoices/<uuid:pk>/", views.sales_invoice_detail, name="sales_invoice_detail"),
    path("receivables/", views.accounts_receivable_view, name="accounts_receivable"),
    path("statement/", views.customer_statement_view, name="customer_statement"),
]
