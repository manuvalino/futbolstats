import json
from django.shortcuts import render
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET
from .services import (
    get_partidos_equipo,
    procesar_rendimiento,
    buscar_equipos,
    elegir_candidato_por_nombre,
)


def _construir_datos_grafica(partidos_encontrados: list[dict], equipo_id: str) -> dict:
    """
    Construye datos para gráfica de barras por partido:
    goles a favor vs goles en contra.
    """
    labels = []
    condiciones = []
    rivales = []
    goles_favor = []
    goles_contra = []
    diferencia_goles = []

    equipo_id_int = int(equipo_id)
    for p in partidos_encontrados:
        home = p.get("homeTeam", {})
        away = p.get("awayTeam", {})
        score = (p.get("score") or {}).get("fullTime", {})

        es_local = home.get("id") == equipo_id_int
        gf = score.get("home") if es_local else score.get("away")
        gc = score.get("away") if es_local else score.get("home")

        if gf is None or gc is None:
            continue

        fecha = (p.get("utcDate") or "")[:10]
        rival = away.get("name", "Rival") if es_local else home.get("name", "Rival")
        condicion = "L" if es_local else "V"

        labels.append(f"{fecha} ({condicion}) vs {rival}")
        condiciones.append(condicion)
        rivales.append(rival)
        goles_favor.append(gf)
        goles_contra.append(gc)
        diferencia_goles.append(gf - gc)

    # Mostrar cronológico en la gráfica para que se lea mejor
    labels.reverse()
    condiciones.reverse()
    rivales.reverse()
    goles_favor.reverse()
    goles_contra.reverse()
    diferencia_goles.reverse()

    return {
        "labels": labels,
        "condiciones": condiciones,
        "rivales": rivales,
        "goles_favor": goles_favor,
        "goles_contra": goles_contra,
        "diferencia_goles": diferencia_goles,
    }


@login_required
def dashboard(request):
    """Pantalla principal — F0."""
    return render(request, "rendimiento/dashboard.html")

@login_required
def index(request):
    context = {
        "equipo_seleccionado": "",
        "query_usada": "",
        "candidatos": None,
    }

    nom_equipo = request.GET.get("equipo", "").strip()
    team_id = request.GET.get("team_id", "").strip()

    context["equipo_seleccionado"] = nom_equipo
    context["query_usada"] = nom_equipo

    try:
        n_partidos = int(request.GET.get("n_partidos", 15))
        n_partidos = max(1, min(n_partidos, 30))
    except ValueError:
        n_partidos = 15
    context["n_partidos"] = n_partidos

    if not nom_equipo and not team_id:
        return render(request, "rendimiento/index.html", context)

    equipo_id = None
    nombre_final = nom_equipo

    try:
        if team_id:
            equipo_id = team_id
        else:
            candidatos = buscar_equipos(nom_equipo)
            if not candidatos:
                context["error_api"] = (
                    f"No se encontró '{nom_equipo}' en football-data.org. "
                    "Comprueba el nombre o usa una sugerencia del autocomplete."
                )
                return render(request, "rendimiento/index.html", context)

            candidato_exacto = elegir_candidato_por_nombre(candidatos, nom_equipo)
            if candidato_exacto:
                equipo_id = candidato_exacto["id"]
                nombre_final = candidato_exacto["nombre"]
            elif len(candidatos) == 1:
                equipo_id = candidatos[0]["id"]
                nombre_final = candidatos[0]["nombre"]
            else:
                context["candidatos"] = candidatos[:8]
                context["error_api"] = (
                    f"Se encontraron {len(candidatos)} equipos. Selecciona el correcto."
                )
                return render(request, "rendimiento/index.html", context)

        partidos_encontrados = get_partidos_equipo(equipo_id, n_partidos)
        resultados = procesar_rendimiento(partidos_encontrados, equipo_id)

        if resultados:
            context["medias"] = resultados.get("medias")
            context["lista_partidos"] = resultados.get("lista_partidos")
            context["grafica_rendimiento_json"] = json.dumps(
                _construir_datos_grafica(partidos_encontrados, equipo_id)
            )

        context["resultados"] = resultados
        context["equipo_id"] = equipo_id
        context["equipo_seleccionado"] = nombre_final
        context["query_usada"] = nombre_final

    except RuntimeError as e:
        context["error_api"] = str(e)

    return render(request, "rendimiento/index.html", context)


@require_GET
def autocomplete_equipos(request):
    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"sugerencias": []})
    try:
        candidatos = buscar_equipos(q)
        sugerencias = [
            {"label": c["nombre"], "id": c["id"], "pais": c["pais"], "logo": c["logo"]}
            for c in candidatos[:8]
        ]
    except RuntimeError:
        sugerencias = []
    return JsonResponse({"sugerencias": sugerencias})
