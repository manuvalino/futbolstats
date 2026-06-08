from django.urls import path
from . import views

app_name = "rachas"
urlpatterns = [
    path("",              views.comparador,                name="comparador"),
    path("autocomplete/", views.autocomplete_competiciones, name="autocomplete"),
]
