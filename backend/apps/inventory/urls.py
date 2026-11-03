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
]
