from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.core.urls")),
    path("organizations/", include("apps.organizations.urls")),
    path("accounting/", include("apps.accounting.urls")),
    path("inventory/", include("apps.inventory.urls")),
    path("parties/", include("apps.parties.urls")),
    path("purchases/", include("apps.purchases.urls")),
    path("sales/", include("apps.sales.urls")),
    path("health/", include("apps.core.health_urls")),
]
