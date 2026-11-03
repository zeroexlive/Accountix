from django.urls import path

from apps.parties import views

urlpatterns = [
    path("", views.party_list, name="party_list"),
    path("new/", views.party_create, name="party_create"),
    path("<uuid:pk>/", views.party_detail, name="party_detail"),
    path("<uuid:pk>/edit/", views.party_edit, name="party_edit"),
]
