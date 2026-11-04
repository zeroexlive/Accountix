from django.urls import path

from apps.core import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    # Barcode/QR scanning (Sprint 31, ADR-060). The literal routes
    # precede the token route so "lookup"/"sessions" can never be
    # parsed as pairing tokens.
    path("scan/lookup/", views.scan_lookup, name="scan_lookup"),
    path("scan/sessions/", views.scan_session_create, name="scan_session_create"),
    path(
        "scan/sessions/<uuid:pk>/results/",
        views.scan_session_results,
        name="scan_session_results",
    ),
    path(
        "scan/sessions/<uuid:pk>/revoke/",
        views.scan_session_revoke,
        name="scan_session_revoke",
    ),
    path("scan/<str:token>/", views.scan_phone_page, name="scan_phone_page"),
    path("scan/<str:token>/submit/", views.scan_phone_submit, name="scan_phone_submit"),
]
