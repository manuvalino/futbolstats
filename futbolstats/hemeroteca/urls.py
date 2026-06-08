from django.urls import path
from . import views

app_name = "hemeroteca"
urlpatterns = [
    path("",              views.hemeroteca,             name="hemeroteca"),
    path("autocomplete/", views.autocomplete_hemeroteca, name="autocomplete"),
]
