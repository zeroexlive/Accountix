from django.urls import path

from apps.organizations import views

urlpatterns = [
    path("companies/", views.company_list, name="company_list"),
    path("companies/new/", views.company_create, name="company_create"),
    path("companies/<uuid:pk>/", views.company_detail, name="company_detail"),
    path("fiscal-years/", views.fiscal_year_list, name="fiscal_year_list"),
    path("fiscal-years/new/", views.fiscal_year_create, name="fiscal_year_create"),
]
