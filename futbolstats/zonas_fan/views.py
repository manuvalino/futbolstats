"""zonas_fan/views.py — F4 Zonas fan y restauración."""

import json
import numpy as np  
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .services import obtener_coordenadas_estadio, buscar_locales_cercanos, buscar_equipos_autocomplete
from django.http import JsonResponse
from django.views.decorators.http import require_GET

EQUIPOS_SUGERIDOS = [
    "RC Deportivo de La Coruña",
    "RC Celta de Vigo",
    "Real Madrid",
    "FC Barcelona",
]


class _NumpyEncoder(json.JSONEncoder):
    """Convierte tipos numpy a tipos Python nativos para json.dumps."""
    def default(self, obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)
@login_required
def zonas(request):
    contexto = {"equipos_sugeridos": EQUIPOS_SUGERIDOS, "locales": None,
                "mapa_lat": None, "mapa_lng": None}

    if request.method == "POST":
        nombre = request.POST.get("equipo", "").strip()
        radio  = int(request.POST.get("radio", 1000))
        if not nombre:
            messages.error(request, "Introduce el nombre de un equipo.")
            return render(request, "zonas_fan/zonas.html", contexto)
        try:
            coords = obtener_coordenadas_estadio(nombre)
            locales = buscar_locales_cercanos(coords["lat"], coords["lng"], radio)
            contexto.update({
                "locales":          locales,
                "estadio":          coords["estadio"],
                "mapa_lat":         float(coords["lat"]),
                "mapa_lng":         float(coords["lng"]),
                "equipo_nombre":    nombre,
                "radio":            radio,
                "locales_json":     json.dumps(locales, cls=_NumpyEncoder),
                # Coordenadas serializadas con json.dumps → punto decimal garantizado
                "mapa_coords_json": json.dumps({"lat": float(coords["lat"]), "lng": float(coords["lng"])}),
})
            if not locales:
                messages.info(request, "No se encontraron locales en ese radio.")
        except RuntimeError as e:
            messages.error(request, str(e))

    return render(request, "zonas_fan/zonas.html", contexto)


# ── Autocomplete endpoint ──────────────────────────────────────
from django.http import JsonResponse  
from django.views.decorators.http import require_GET

EQUIPOS_ZONAS = [
    "RC Deportivo de La Coruña", "RC Celta de Vigo", "Real Madrid",
    "FC Barcelona", "Atletico Madrid", "Athletic Club",
    "Real Sociedad", "Sevilla FC", "Real Betis", "Villarreal CF",
]



@require_GET
@login_required
def autocomplete_equipos(request):
    """Devuelve equipos desde API-Football para el autocomplete del mapa."""
    q = request.GET.get("q", "").strip()
    if len(q) < 2:                          # mínimo 2 chars para no disparar calls vacías
        return JsonResponse({"sugerencias": []})
    sugerencias = buscar_equipos_autocomplete(q)
    return JsonResponse({"sugerencias": sugerencias})
