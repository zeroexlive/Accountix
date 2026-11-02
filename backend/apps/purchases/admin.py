from django.contrib import admin

from apps.purchases.models import PurchaseInvoice, PurchaseOrder, PurchaseReturn

admin.site.register(PurchaseOrder)
admin.site.register(PurchaseInvoice)
admin.site.register(PurchaseReturn)
