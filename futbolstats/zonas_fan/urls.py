from django.urls import path
from . import views

app_name = "zonas_fan"
urlpatterns = [
    path("",              views.zonas,              name="zonas"),
    path("autocomplete/", views.autocomplete_equipos, name="autocomplete"),
]
