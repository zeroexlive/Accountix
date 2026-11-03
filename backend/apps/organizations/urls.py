from django.urls import path

from apps.organizations import views

urlpatterns = [
    path("companies/", views.company_list, name="company_list"),
    path("companies/new/", views.company_create, name="company_create"),
    path("companies/<uuid:pk>/", views.company_detail, name="company_detail"),
    path("companies/<uuid:pk>/members/", views.company_members, name="company_members"),
    path(
        "companies/<uuid:pk>/members/add-existing/",
        views.company_member_add_existing,
        name="company_member_add_existing",
    ),
    path(
        "companies/<uuid:pk>/members/add-new/",
        views.company_member_add_new,
        name="company_member_add_new",
    ),
    path(
        "companies/<uuid:pk>/members/<uuid:member_pk>/role/",
        views.company_member_role,
        name="company_member_role",
    ),
    path(
        "companies/<uuid:pk>/members/<uuid:member_pk>/deactivate/",
        views.company_member_deactivate,
        name="company_member_deactivate",
    ),
    path(
        "companies/<uuid:pk>/members/<uuid:member_pk>/reactivate/",
        views.company_member_reactivate,
        name="company_member_reactivate",
    ),
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
