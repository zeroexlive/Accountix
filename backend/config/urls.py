from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    # Language switcher endpoint (Sprint 19, ADR-045): Django's
    # set_language view at /i18n/setlang/ — POST-only, stores the
    # choice in the language cookie; URLs themselves are not prefixed.
    path("i18n/", include("django.conf.urls.i18n")),
    # Login + first-run setup (Sprint 24, ADR-049): the users app owns
    # both; its login view redirects a zero-user install to /setup/.
    path("", include("apps.users.urls")),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("parties/", include("apps.parties.urls")),
    path("purchases/", include("apps.purchases.urls")),
    path("sales/", include("apps.sales.urls")),
    path("treasury/", include("apps.treasury.urls")),
    path("reports/", include("apps.reporting.urls")),
    path("health/", include("apps.core.health_urls")),
]
