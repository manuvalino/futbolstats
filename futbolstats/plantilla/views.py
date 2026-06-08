"""plantilla/views.py — F3 Valor de mercado (API-Football v3)."""

from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_GET

from .services import (
    buscar_equipos,
    elegir_candidato_por_nombre,
    obtener_info_equipo,
    obtener_plantilla,
    obtener_fees_transferencias,
    analizar_valor_plantilla,
)

EQUIPOS_SUGERIDOS = [
    "RC Deportivo de La Coruña",
    "RC Celta de Vigo",
    "Real Madrid",
    "FC Barcelona",
    "Atletico Madrid",
]


@login_required
def valor_mercado(request):
    contexto = {
        "equipos_sugeridos": EQUIPOS_SUGERIDOS,
        "resultado":         None,
        "candidatos":        None,
        "query_usada":       "",
    }

    if request.method != "POST":
        return render(request, "plantilla/valor_mercado.html", contexto)

    nombre  = request.POST.get("equipo", "").strip()
    team_id = request.POST.get("team_id", "").strip()
    contexto["query_usada"] = nombre

    if not nombre and not team_id:
        messages.error(request, "Introduce el nombre de un equipo.")
        return render(request, "plantilla/valor_mercado.html", contexto)

    try:
        if team_id:
            _cargar_plantilla(request, contexto, team_id, nombre)
            return render(request, "plantilla/valor_mercado.html", contexto)

        candidatos = buscar_equipos(nombre)

        if not candidatos:
            messages.warning(
                request,
                f"No hemos encontrado '{nombre}' en API-Football. "
                "Revisa si el nombre está bien escrito o prueba con otra forma de llamarlo.",
            )
        elif (candidato_exacto := elegir_candidato_por_nombre(candidatos, nombre)):
            _cargar_plantilla(
                request,
                contexto,
                candidato_exacto["id"],
                candidato_exacto["nombre"],
            )
        elif len(candidatos) == 1:
            _cargar_plantilla(request, contexto, candidatos[0]["id"], candidatos[0]["nombre"])
        else:
            contexto["candidatos"]  = candidatos
            messages.info(request, f"Se encontraron {len(candidatos)} equipos. Selecciona el correcto:")

    except RuntimeError as e:
        messages.error(request, str(e))

    return render(request, "plantilla/valor_mercado.html", contexto)


def _cargar_plantilla(request, contexto: dict, team_id: str, nombre_fallback: str):
    """
    Obtiene plantilla + fees de transferencia en paralelo (dos llamadas),
    cruzamos los datos con Pandas y rellena el contexto.
    """
    equipo    = obtener_info_equipo(team_id)
    jugadores = obtener_plantilla(team_id)

    if not jugadores:
        messages.warning(
            request,
            "No se encontraron jugadores para este equipo en API-Football. "
            "Es posible que el endpoint /players/squads requiera un plan de pago. "
            "Prueba con otro equipo o contacta con el administrador.",
        )
        return

    # Segunda llamada: fees de transferencia (falla silenciosamente si hay error)
    fees = obtener_fees_transferencias(team_id)

    resultado = analizar_valor_plantilla(jugadores, fees)

    if "error" in resultado:
        messages.warning(request, resultado["error"])
    else:
        contexto["resultado"]     = resultado
        contexto["equipo_nombre"] = equipo.get("nombre", nombre_fallback)
        contexto["escudo_url"]    = equipo.get("logo", "")
        contexto["equipo_pais"]   = equipo.get("pais", "")


@require_GET
@login_required
def autocomplete_equipos(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"sugerencias": []})
    try:
        candidatos  = buscar_equipos(q)
        sugerencias = [
            {"label": c["nombre"], "id": c["id"], "pais": c["pais"], "logo": c["logo"]}
            for c in candidatos[:8]
        ]
    except Exception:
        sugerencias = []
    return JsonResponse({"sugerencias": sugerencias})