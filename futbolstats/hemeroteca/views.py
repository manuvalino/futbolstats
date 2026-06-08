"""
hemeroteca/views.py
F5 — Hemeroteca y resúmenes en vídeo (solo YouTube Data API v3).
Los vídeos se reproducen embebidos en la propia web mediante iframe.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_GET

from .services import buscar_videos_youtube, construir_query

# Sugerencias para el autocomplete — equipos y partidos históricos conocidos
SUGERENCIAS_HEMEROTECA = [
    "RC Deportivo de La Coruña",
    "RC Deportivo de La Coruña vs AC Milan 2004",
    "Deportivo 4 – 0 AC Milan 2004",
    "RC Deportivo vs Paris Saint-Germain 2001",
    "RC Deportivo Campeón Liga 2000",
    "RC Deportivo vs Valencia CF",
    "RC Deportivo vs Real Madrid",
    "RC Celta de Vigo",
    "Real Madrid CF",
    "FC Barcelona",
    "Club Atlético de Madrid",
    "Selección española",
]


@login_required
def hemeroteca(request):
    """Vista principal F5."""
    contexto = {
        "videos":      None,
        "query_usada": "",
        "sugerencias": SUGERENCIAS_HEMEROTECA,
    }

    if request.method == "POST":
        texto = request.POST.get("busqueda", "").strip()
        if not texto:
            messages.error(request, "Introduce el nombre de un partido o equipo.")
            return render(request, "hemeroteca/hemeroteca.html", contexto)

        query = construir_query(texto)
        contexto["query_usada"] = texto

        try:
            videos = buscar_videos_youtube(query, max_results=9)
            if not videos:
                messages.info(request, "No se encontraron vídeos para esa búsqueda. Prueba con otro término.")
            contexto["videos"] = videos
        except RuntimeError as e:
            messages.error(request, str(e))

    return render(request, "hemeroteca/hemeroteca.html", contexto)


@require_GET
@login_required
def autocomplete_hemeroteca(request):
    """
    Endpoint AJAX para autocomplete.
    Devuelve sugerencias filtradas por el término introducido.
    """
    q = request.GET.get("q", "").strip().lower()
    if len(q) < 2:
        return JsonResponse({"sugerencias": []})

    resultados = [
        s for s in SUGERENCIAS_HEMEROTECA
        if q in s.lower()
    ][:8]
    return JsonResponse({"sugerencias": resultados})
