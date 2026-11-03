from django.urls import path

from apps.inventory import views

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_create, name="product_create"),
    path("products/<uuid:pk>/edit/", views.product_edit, name="product_edit"),
    path("units/new/", views.unit_create, name="unit_create"),
    path("categories/new/", views.category_create, name="category_create"),
    path("warehouses/new/", views.warehouse_create, name="warehouse_create"),
    path("stock/", views.stock_balance_list, name="stock_balances"),
    path("movements/", views.stock_movement_list, name="stock_movements"),
    path("counts/", views.inventory_count_list, name="inventory_counts"),
    path("counts/new/", views.inventory_count_create, name="inventory_count_create"),
    path("counts/<uuid:pk>/", views.inventory_count_detail, name="inventory_count_detail"),
    path("counts/<uuid:pk>/save/", views.inventory_count_save, name="inventory_count_save"),
    path("counts/<uuid:pk>/post/", views.inventory_count_post, name="inventory_count_post"),
    path(
        "counts/<uuid:pk>/reverse/",
        views.inventory_count_reverse,
        name="inventory_count_reverse",
    ),
]
