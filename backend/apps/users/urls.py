from django.urls import path

from apps.users import views

urlpatterns = [
    path("login/", views.SetupAwareLoginView.as_view(), name="login"),
    path("setup/", views.first_run_setup, name="setup"),
    # Self-service account surface (Sprint 27, ADR-052): self-only by
    # construction — no user id in the URL, the subject is always
    # request.user.
    path("profile/", views.profile, name="profile"),
    path("profile/password/", views.AccountPasswordChangeView.as_view(), name="password_change"),
]
