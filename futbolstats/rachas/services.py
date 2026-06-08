import requests
import pandas as pd
from django.conf import settings

FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"


def _headers() -> dict:
    return {"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY}

COMPETICIONES = {
    "LaLiga Hypermotion":  "SL2",
    "LaLiga EA Sports":    "PD",
    "Premier League":      "PL",
    "Bundesliga":          "BL1",
    "Serie A":             "SA",
    "Ligue 1":             "FL1",
}

# Competición mostrada por defecto al entrar en la sección
COMPETICION_DEFAULT = "LaLiga EA Sports"


def obtener_clasificacion_oficial(competicion_code: str) -> list[dict]:
    """
    Descarga la clasificación oficial actual de la competición.
    Devuelve lista de {pos, equipo, puntos, pg, pe, pp, gf, gc, dg}.
    """
    url = f"{FOOTBALL_DATA_BASE}/competitions/{competicion_code}/standings"
    try:
        r = requests.get(url, headers=_headers(), timeout=10)
        r.raise_for_status()
        standings = r.json().get("standings", [])
        # standings[0] = clasificación general (TOTAL)
        tabla = next((s for s in standings if s.get("type") == "TOTAL"), standings[0] if standings else None)
        if not tabla:
            return []
        filas = []
        for entry in tabla.get("table", []):
            filas.append({
                "pos":    entry["position"],
                "equipo": entry["team"]["name"],
                "puntos": entry["points"],
                "pg":     entry["won"],
                "pe":     entry["draw"],
                "pp":     entry["lost"],
                "gf":     entry["goalsFor"],
                "gc":     entry["goalsAgainst"],
                "dg":     entry["goalDifference"],
                "pj":     entry["playedGames"],
            })
        return filas
    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code if e.response is not None else "desconocido"
        if codigo == 403:
            raise RuntimeError(
                "football-data.org rechazó la clasificación (HTTP 403). "
                "Suele deberse a token inválido o permisos del plan para esa competición."
            )
        if codigo == 429:
            raise RuntimeError("Se alcanzó el límite de peticiones de football-data.org.")
        raise RuntimeError(f"Error al obtener clasificación de football-data.org (HTTP {codigo}).")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error al conectar con football-data.org: {e}")


def obtener_resultados_temporada(competicion_code: str) -> list[dict]:
    """Descarga todos los partidos FINISHED de la temporada actual."""
    url = f"{FOOTBALL_DATA_BASE}/competitions/{competicion_code}/matches"
    try:
        r = requests.get(url, headers=_headers(), params={"status": "FINISHED"}, timeout=10)
        r.raise_for_status()
        return r.json().get("matches", [])
    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code if e.response is not None else "desconocido"
        if codigo == 429:
            raise RuntimeError("Se alcanzó el límite de peticiones de football-data.org.")
        raise RuntimeError(f"Error al conectar con football-data.org (HTTP {codigo}).")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error al conectar con football-data.org: {e}")


def calcular_ranking_forma(partidos: list[dict], n_partidos: int = 5,
                           clasificacion_oficial: list[dict] | None = None) -> list[dict]:
    """
    - Calcula puntos por partido para cada equipo
    """
    if not partidos:
        return []

    filas = []
    for p in partidos:
        g_l = p["score"]["fullTime"]["home"]
        g_v = p["score"]["fullTime"]["away"]
        if g_l is None or g_v is None:
            continue
        if g_l > g_v:
            pts_l, pts_v, res_l, res_v = 3, 0, "V", "D"
        elif g_l == g_v:
            pts_l, pts_v, res_l, res_v = 1, 1, "E", "E"
        else:
            pts_l, pts_v, res_l, res_v = 0, 3, "D", "V"

        filas.append({"equipo": p["homeTeam"]["name"], "puntos": pts_l,
                      "resultado": res_l, "fecha": p["utcDate"][:10]})
        filas.append({"equipo": p["awayTeam"]["name"], "puntos": pts_v,
                      "resultado": res_v, "fecha": p["utcDate"][:10]})

    if not filas:
        return []

    df = pd.DataFrame(filas)
    df["fecha"] = pd.to_datetime(df["fecha"])
    df = df.sort_values("fecha")

    # Últimos N partidos por equipo 
    ultimos_n = df.groupby("equipo").tail(n_partidos)

    # Puntos de racha y secuencia de resultados
    racha_pts = (
        ultimos_n.groupby("equipo")
        .agg(racha_pts=("puntos", "sum"), partidos_racha=("puntos", "count"))
        .reset_index()
    )
    racha_lista = (
        ultimos_n.groupby("equipo")["resultado"]
        .apply(list)
        .reset_index()
        .rename(columns={"resultado": "racha_lista"})
    )
    racha = racha_pts.merge(racha_lista, on="equipo")
    racha = racha.sort_values("racha_pts", ascending=False).reset_index(drop=True)
    racha["pos_racha"] = racha.index + 1

    # Merge con clasificación oficial para Δ posición
    if clasificacion_oficial:
        df_oficial = pd.DataFrame(clasificacion_oficial)[["pos", "equipo"]]
        racha = racha.merge(df_oficial, on="equipo", how="left")
        racha["delta_pos"] = racha["pos"].fillna(0).astype(int) - racha["pos_racha"]
    else:
        racha["pos"] = None
        racha["delta_pos"] = None

    return racha.to_dict(orient="records")
