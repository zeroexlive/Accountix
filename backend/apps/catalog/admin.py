from django.contrib import admin

from apps.catalog.models import Product, ProductCategory, ProductUnitConversion, Unit

admin.site.register(Unit)
admin.site.register(ProductCategory)
admin.site.register(Product)
admin.site.register(ProductUnitConversion)
