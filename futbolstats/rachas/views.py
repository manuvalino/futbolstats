"""
En GET: carga la clasificación oficial actual por defecto.
En POST: calcula el ranking de forma con N partidos configurable.
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_GET

from .services import (
    COMPETICIONES, COMPETICION_DEFAULT,
    obtener_clasificacion_oficial,
    obtener_resultados_temporada,
    calcular_ranking_forma,
)


@login_required
def comparador(request):
    # Competición activa: la del POST o la default
    comp_nombre = request.POST.get("competicion", COMPETICION_DEFAULT) if request.method == "POST" \
                  else COMPETICION_DEFAULT
    comp_code   = COMPETICIONES.get(comp_nombre, COMPETICIONES[COMPETICION_DEFAULT])

    try:
        n_partidos = int(request.POST.get("n_partidos", 5)) if request.method == "POST" else 5
        n_partidos = max(1, min(n_partidos, 38))
    except ValueError:
        n_partidos = 5

    contexto = {
        "competiciones":       list(COMPETICIONES.keys()),
        "competicion_nombre":  comp_nombre,
        "n_partidos":          n_partidos,
        "clasificacion":       None,   # tabla oficial
        "ranking":             None,   # tabla de forma
        "mostrar_forma":       False,
    }

    # ── Siempre: clasificación oficial actual ──────────────────
    try:
        clasificacion = obtener_clasificacion_oficial(comp_code)
        contexto["clasificacion"] = clasificacion
    except RuntimeError as e:
        messages.error(request, str(e))
        return render(request, "rachas/comparador.html", contexto)

    # ── Solo en POST: calcular ranking de forma ────────────────
    if request.method == "POST":
        try:
            partidos = obtener_resultados_temporada(comp_code)
            ranking  = calcular_ranking_forma(partidos, n_partidos, clasificacion)
            if not ranking:
                messages.warning(request, "No hay suficientes partidos disputados para calcular rachas.")
            else:
                contexto["ranking"]       = ranking
                contexto["mostrar_forma"] = True
        except RuntimeError as e:
            messages.error(request, str(e))

    return render(request, "rachas/comparador.html", contexto)


@require_GET
@login_required
def autocomplete_competiciones(request):
    """Endpoint AJAX para autocomplete de competiciones"""
    q = request.GET.get("q", "").strip().lower()
    resultados = [c for c in COMPETICIONES if q in c.lower()][:8]
    return JsonResponse({"sugerencias": resultados})
