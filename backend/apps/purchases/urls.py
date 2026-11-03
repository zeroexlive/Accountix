from django.urls import path

from apps.purchases import views

urlpatterns = [
    path("invoices/", views.purchase_invoice_list, name="purchase_invoice_list"),
    path("invoices/new/", views.purchase_invoice_create, name="purchase_invoice_create"),
    path("invoices/<uuid:pk>/", views.purchase_invoice_detail, name="purchase_invoice_detail"),
    path("invoices/<uuid:pk>/post/", views.purchase_invoice_post, name="purchase_invoice_post"),
    path(
        "invoices/<uuid:pk>/reverse/",
        views.purchase_invoice_reverse,
        name="purchase_invoice_reverse",
    ),
    path(
        "invoices/<uuid:pk>/returns/new/",
        views.purchase_return_create,
        name="purchase_return_create",
    ),
    path("invoices/<uuid:pk>/print/", views.purchase_invoice_print, name="purchase_invoice_print"),
    path("returns/<uuid:pk>/", views.purchase_return_detail, name="purchase_return_detail"),
    path("returns/<uuid:pk>/post/", views.purchase_return_post, name="purchase_return_post"),
    path(
        "returns/<uuid:pk>/reverse/",
        views.purchase_return_reverse,
        name="purchase_return_reverse",
    ),
    path("statement/print/", views.supplier_statement_print, name="supplier_statement_print"),
    path("payables/", views.accounts_payable_view, name="accounts_payable"),
]
