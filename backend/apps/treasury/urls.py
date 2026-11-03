from django.urls import path

from apps.treasury import views

urlpatterns = [
    path("accounts/", views.treasury_account_list, name="treasury_account_list"),
    path("accounts/new/", views.treasury_account_create, name="treasury_account_create"),
    path("payments/", views.payment_list, name="payment_list"),
    path("payments/new/", views.payment_create, name="payment_create"),
    path("payments/<uuid:pk>/", views.payment_detail, name="payment_detail"),
    path("payments/<uuid:pk>/post/", views.payment_post, name="payment_post"),
    path("payments/<uuid:pk>/reverse/", views.payment_reverse, name="payment_reverse"),
    path("payments/<uuid:pk>/allocate/", views.payment_allocate, name="payment_allocate"),
    path(
        "payments/<uuid:pk>/allocations/<uuid:alloc_pk>/void/",
        views.allocation_void,
        name="allocation_void",
    ),
    path("cheques/", views.cheque_list, name="cheque_list"),
    path("cheques/<uuid:pk>/", views.cheque_detail, name="cheque_detail"),
    path("cheques/<uuid:pk>/deposit/", views.cheque_deposit, name="cheque_deposit"),
    path("cheques/<uuid:pk>/clear/", views.cheque_clear, name="cheque_clear"),
    path("cheques/<uuid:pk>/bounce/", views.cheque_bounce, name="cheque_bounce"),
    path("cheques/<uuid:pk>/return/", views.cheque_return, name="cheque_return"),
    path("open-items/", views.open_items_view, name="treasury_open_items"),
    path("statements/", views.bank_statement_list, name="bank_statement_list"),
    path("statements/new/", views.bank_statement_create, name="bank_statement_create"),
    path("statements/<uuid:pk>/", views.bank_statement_detail, name="bank_statement_detail"),
    path(
        "statements/<uuid:pk>/lines/add/",
        views.bank_statement_add_line,
        name="bank_statement_add_line",
    ),
    path("statements/<uuid:pk>/import/", views.bank_statement_import, name="bank_statement_import"),
    path(
        "statements/<uuid:pk>/auto-match/",
        views.bank_statement_auto_match,
        name="bank_statement_auto_match",
    ),
    path("statements/<uuid:pk>/match/", views.bank_statement_match, name="bank_statement_match"),
    path(
        "statements/<uuid:pk>/lines/<uuid:line_pk>/unmatch/",
        views.bank_statement_unmatch,
        name="bank_statement_unmatch",
    ),
    path(
        "statements/<uuid:pk>/complete/",
        views.bank_statement_complete,
        name="bank_statement_complete",
    ),
    path("statements/<uuid:pk>/reopen/", views.bank_statement_reopen, name="bank_statement_reopen"),
]
