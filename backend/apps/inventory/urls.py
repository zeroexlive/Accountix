from django.urls import path

from apps.inventory import views

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("stock/", views.stock_balance_list, name="stock_balances"),
    path("counts/", views.inventory_count_list, name="inventory_counts"),
]
