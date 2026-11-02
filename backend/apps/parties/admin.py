from django.contrib import admin

from apps.parties.models import Party, PartyAddress, PartyContact

admin.site.register(Party)
admin.site.register(PartyContact)
admin.site.register(PartyAddress)
