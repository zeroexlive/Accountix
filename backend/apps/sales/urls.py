from django.urls import path

from apps.sales import views

urlpatterns = [
    path("invoices/", views.sales_invoice_list, name="sales_invoice_list"),
    path("invoices/new/", views.sales_invoice_create, name="sales_invoice_create"),
    path("invoices/<uuid:pk>/", views.sales_invoice_detail, name="sales_invoice_detail"),
    path("invoices/<uuid:pk>/post/", views.sales_invoice_post, name="sales_invoice_post"),
    path("invoices/<uuid:pk>/reverse/", views.sales_invoice_reverse, name="sales_invoice_reverse"),
    path("invoices/<uuid:pk>/returns/new/", views.sales_return_create, name="sales_return_create"),
    path("invoices/<uuid:pk>/print/", views.sales_invoice_print, name="sales_invoice_print"),
    path("returns/<uuid:pk>/", views.sales_return_detail, name="sales_return_detail"),
    path("returns/<uuid:pk>/post/", views.sales_return_post, name="sales_return_post"),
    path("returns/<uuid:pk>/reverse/", views.sales_return_reverse, name="sales_return_reverse"),
    path("statement/print/", views.customer_statement_print, name="customer_statement_print"),
    path("receivables/", views.accounts_receivable_view, name="accounts_receivable"),
    path("statement/", views.customer_statement_view, name="customer_statement"),
]
