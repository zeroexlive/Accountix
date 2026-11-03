from django.urls import path

from apps.organizations import views

urlpatterns = [
    path("companies/", views.company_list, name="company_list"),
    path("companies/new/", views.company_create, name="company_create"),
    path("companies/<uuid:pk>/", views.company_detail, name="company_detail"),
    path("fiscal-years/", views.fiscal_year_list, name="fiscal_year_list"),
    path("fiscal-years/new/", views.fiscal_year_create, name="fiscal_year_create"),
    path("fiscal-years/<uuid:pk>/", views.fiscal_year_detail, name="fiscal_year_detail"),
    path("fiscal-years/<uuid:pk>/close/", views.fiscal_year_close, name="fiscal_year_close"),
    path(
        "fiscal-periods/<uuid:pk>/close/",
        views.fiscal_period_close,
        name="fiscal_period_close",
    ),
    path(
        "fiscal-periods/<uuid:pk>/reopen/",
        views.fiscal_period_reopen,
        name="fiscal_period_reopen",
    ),
]
