from django.contrib import admin

from apps.organizations.models import Branch, Company, CompanyMembership, FiscalPeriod, FiscalYear

admin.site.register([Company, Branch, CompanyMembership, FiscalYear, FiscalPeriod])
