from django.contrib import admin

from apps.treasury.models import Cheque, Payment, PaymentAllocation, TreasuryAccount

admin.site.register(TreasuryAccount)
admin.site.register(Payment)
admin.site.register(PaymentAllocation)
admin.site.register(Cheque)
