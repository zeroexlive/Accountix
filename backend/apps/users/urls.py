from django.urls import path

from apps.users import views

urlpatterns = [
    path("login/", views.SetupAwareLoginView.as_view(), name="login"),
    path("setup/", views.first_run_setup, name="setup"),
]
