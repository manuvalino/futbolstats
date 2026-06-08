"""
FutbolStats — urls.py raíz
Enruta a cada aplicación Django.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),

    # Autenticación (login, logout, registro)
    path("accounts/", include("accounts.urls")),

    # Funcionalidades principales
    path("", include("rendimiento.urls")),          # dashboard en /
    path("rachas/", include("rachas.urls")),
    path("plantilla/", include("plantilla.urls")),
    path("zonas-fan/", include("zonas_fan.urls")),
    path("hemeroteca/", include("hemeroteca.urls")),
]

# Páginas de error personalizadas (rúbrica C5 y C9)
handler404 = "futbolstats.views.error_404"
handler500 = "futbolstats.views.error_500"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
