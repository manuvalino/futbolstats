from django.urls import path
from . import views

app_name = "rendimiento"
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path("rendimiento/", views.index, name="index"),
    path("rendimiento/autocomplete/", views.autocomplete_equipos, name="autocomplete"),
]
