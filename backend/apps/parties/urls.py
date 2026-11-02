from django.urls import path

from apps.parties import views

urlpatterns = [
    path("", views.party_list, name="party_list"),
]
