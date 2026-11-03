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
]
