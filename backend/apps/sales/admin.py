from django.contrib import admin

from apps.sales.models import SalesInvoice, SalesQuotation, SalesReturn

admin.site.register(SalesQuotation)
admin.site.register(SalesInvoice)
admin.site.register(SalesReturn)
