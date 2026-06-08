from django.urls import path
from . import views

app_name = "plantilla"
urlpatterns = [
    path("",              views.valor_mercado,     name="valor_mercado"),
    path("autocomplete/", views.autocomplete_equipos, name="autocomplete"),
]
