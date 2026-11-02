from django.contrib import admin

from apps.inventory.models import InventoryCount, StockDocument, StockMovement, Warehouse

admin.site.register(Warehouse)
admin.site.register(StockDocument)
admin.site.register(StockMovement)
admin.site.register(InventoryCount)
