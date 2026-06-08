"""
zonas_fan/services.py
F4 — Zonas fan y restauración. Multi-API: API-Football (estadio) + OSM/Overpass (locales).
En este archivo nos ayudamos de la herramienta de IA Cursor
"""

import requests
import pandas as pd
import overpy
import time
from math import radians, sin, cos, sqrt, atan2
from django.conf import settings

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
# Overpass suele saturarse , usamos servidores alternativos(mirrors) por si uno falla y backoff corto
# para ser mas consistentes
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
OVERPASS_BACKOFF_SECONDS = [0.8, 1.6]
MAX_LOCALES = 40

API_FOOTBALL_HEADERS = {
    "x-apisports-key": settings.API_FOOTBALL_KEY,
}


def obtener_coordenadas_estadio(nombre_equipo: str) -> dict:
    """
    Obtiene nombre y coordenadas del estadio.
    Flujo: API-Football (nombre estadio + ciudad) → Nominatim OSM (geocoding).
    API-Football no expone lat/lng en sus respuestas, por eso se delega
    la geocodificación a Nominatim.
    """
    if not settings.API_FOOTBALL_KEY:
        raise RuntimeError("Falta API_FOOTBALL_KEY en el archivo .env.")

    # ── 1. API-Football: nombre del equipo → datos del estadio ──────────
    try:
        r_eq = requests.get(
            f"{API_FOOTBALL_BASE}/teams",
            headers=API_FOOTBALL_HEADERS,
            params={"search": nombre_equipo},
            timeout=10,
        )
        r_eq.raise_for_status()
        payload_eq = r_eq.json()

        errores_api = payload_eq.get("errors") or {}
        if errores_api:
            msg_error = " ".join(str(v) for v in errores_api.values()).strip()
            msg_error_lc = msg_error.lower()
            if "suspended" in msg_error_lc:
                raise RuntimeError(
                    "API-Football indica que la cuenta está suspendida. "
                    "Revisa la clave en el dashboard de API-Football."
                )
            if "request limit" in msg_error_lc or "reached the request limit" in msg_error_lc:
                raise RuntimeError(
                    "No se puede buscar ese equipo porque API-Football ha "
                    "alcanzado el límite diario de peticiones."
                )
            raise RuntimeError(f"API-Football devolvió un error: {msg_error}")

        equipos = payload_eq.get("response", [])
        if not equipos or not isinstance(equipos, list):
            raise RuntimeError(
                f"No se encuentra el estadio '{nombre_equipo}'. "
                "Puede que no exista o que no esté disponible en la API."
            )

        # Preferir coincidencia exacta de nombre.
        eq = next(
            (e for e in equipos
             if e.get("team", {}).get("name", "").lower() == nombre_equipo.lower()),
            equipos[0],
        )

        venue      = eq.get("venue", {})
        estadio    = venue.get("name") or nombre_equipo
        ciudad     = venue.get("city", "")
        pais       = eq.get("team", {}).get("country", "")

    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Error al conectar con API-Football: {e}")

    # ── 2. Nominatim (OSM): geocodificar nombre del estadio ─────────────
    # API-Football no incluye lat/lng en sus respuestas;
    # usamos Nominatim como segunda fuente, encadenando intentos
    # de lo más específico a lo más general.
    coords = (
        _geocodificar_nominatim(f"{estadio}, {ciudad}, {pais}")
        or _geocodificar_nominatim(f"{estadio}, {ciudad}")
        or _geocodificar_nominatim(estadio)
    )

    if not coords:
        raise RuntimeError(
            f"No se encuentra el estadio '{nombre_equipo}'. "
            "Puede que no exista o que no esté disponible en la API."
        )

    return {"estadio": estadio, "lat": coords[0], "lng": coords[1]}


def _geocodificar_nominatim(query: str) -> tuple | None:
    """
    Geocodifica una dirección con Nominatim (OSM).
    Devuelve (lat, lng) o None si no encuentra resultados.
    """
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1},
            headers={"User-Agent": "FutbolStats-GEI-UDC/1.0 (proyecto universitario)"},
            timeout=8,
        )
        r.raise_for_status()
        resultados = r.json()
        if resultados:
            return float(resultados[0]["lat"]), float(resultados[0]["lon"])
    except Exception:
        pass
    return None


def _parsear_coords(lat: str | float | None, lng: str | float | None) -> tuple | None:
    """Intenta parsear lat/lng de API-Football."""
    try:
        if lat is None or lng is None:
            return None
        return float(lat), float(lng)
    except (ValueError, TypeError):
        pass
    return None


def buscar_locales_cercanos(lat: float, lng: float, radio_m: int = 1000) -> list[dict]:
    """
    Overpass (OpenStreetMap): busca bares y restaurantes en radio dado.
    Pandas: normaliza campos y ordena por distancia.
    """
    query = f"""
    [out:json][timeout:25];
    (
      node[amenity=bar](around:{radio_m},{lat},{lng});
      node[amenity=pub](around:{radio_m},{lat},{lng});
      node[amenity=restaurant](around:{radio_m},{lat},{lng});
      node[amenity=cafe](around:{radio_m},{lat},{lng});
      way[amenity=bar](around:{radio_m},{lat},{lng});
      way[amenity=pub](around:{radio_m},{lat},{lng});
      way[amenity=restaurant](around:{radio_m},{lat},{lng});
      way[amenity=cafe](around:{radio_m},{lat},{lng});
      relation[amenity=bar](around:{radio_m},{lat},{lng});
      relation[amenity=pub](around:{radio_m},{lat},{lng});
      relation[amenity=restaurant](around:{radio_m},{lat},{lng});
      relation[amenity=cafe](around:{radio_m},{lat},{lng});
    );
    out center;
    """
    try:
        result = _ejecutar_query_overpass(query)
        resultados = []
        for node in result.nodes:
            resultados.append({
                "type": "node",
                "lat": node.lat,
                "lon": node.lon,
                "tags": node.tags,
            })
        for way in result.ways:
            resultados.append({
                "type": "way",
                "center": {"lat": getattr(way, "center_lat", None), "lon": getattr(way, "center_lon", None)},
                "tags": way.tags,
            })
        for relation in result.relations:
            resultados.append({
                "type": "relation",
                "center": {"lat": getattr(relation, "center_lat", None), "lon": getattr(relation, "center_lon", None)},
                "tags": relation.tags,
            })
    except Exception as e:
        raise RuntimeError(f"Error al conectar con OpenStreetMap/Overpass: {e}")

    if not resultados:
        return []

    # Convertir a DataFrame y limpiar
    filas = []
    for lugar in resultados:
        tags = lugar.get("tags", {})
        categoria = _traducir_amenity(tags.get("amenity"))
        nombre = tags.get("name") or f"{categoria} sin nombre"
        lat_local = lugar.get("lat", lugar.get("center", {}).get("lat"))
        lng_local = lugar.get("lon", lugar.get("center", {}).get("lon"))
        if lat_local is None or lng_local is None:
            continue
        distancia = _distancia_metros(lat, lng, float(lat_local), float(lng_local))
        # Filtro por radio
        if distancia > radio_m:
            continue
        filas.append({
            "nombre":      nombre,
            "categoria":   categoria,
            "distancia":   distancia,
            "direccion":   _direccion_desde_tags(tags),
            "lat":         float(lat_local),
            "lng":         float(lng_local),
        })

    if not filas:
        return []

    df = pd.DataFrame(filas)
    # Priorizamos cercania.
    df_final = df.sort_values("distancia", ascending=True).reset_index(drop=True)
    df_final["distancia"] = df_final["distancia"].astype(int)
    df_final = df_final.head(MAX_LOCALES)

    # Convertir tipos numpy a Python nativos para que json.dumps funcione
    registros = df_final.to_dict(orient="records")
    for r in registros:
        r["distancia"] = int(r["distancia"])
        r["lat"]       = float(r["lat"])
        r["lng"]       = float(r["lng"])
    return registros


def _ejecutar_query_overpass(query: str):
    """
    Ejecuta la query probando mirrors en cascada y con retry corto.
    """
    errores = []
    for mirror in OVERPASS_MIRRORS:
        api = overpy.Overpass(url=mirror)
        for intento in range(len(OVERPASS_BACKOFF_SECONDS) + 1):
            try:
                return api.query(query)
            except Exception as e:
                msg = str(e)
                errores.append(f"{mirror} (intento {intento + 1}): {msg}")
                if _es_error_transitorio_overpass(msg) and intento < len(OVERPASS_BACKOFF_SECONDS):
                    time.sleep(OVERPASS_BACKOFF_SECONDS[intento])
                    continue
                break

    raise RuntimeError(
        "Servicio de locales temporalmente saturado (OpenStreetMap/Overpass). "
        "Reintenta en 30 segundos."
    )


def _es_error_transitorio_overpass(msg: str) -> bool:
    """
    Detección simple de errores transitorios para activar retry.
    """
    texto = (msg or "").lower()
    claves = ["timeout", "timed out", "too high", "429", "502", "503", "504", "rate limit", "406"]
    return any(c in texto for c in claves)


def _traducir_amenity(amenity: str | None) -> str:
    mapa = {
        "bar": "Bar",
        "pub": "Pub",
        "restaurant": "Restaurante",
        "cafe": "Cafeteria",
    }
    return mapa.get((amenity or "").lower(), "Local")


def _direccion_desde_tags(tags: dict) -> str:
    """Construye una direccion legible con datos de OSM si existen."""
    calle = tags.get("addr:street", "")
    numero = tags.get("addr:housenumber", "")
    ciudad = tags.get("addr:city", "")
    partes = [p for p in [f"{calle} {numero}".strip(), ciudad] if p]
    return ", ".join(partes) if partes else "N/A"


def _distancia_metros(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6371000.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return int(r * c)


def buscar_equipos_autocomplete(query: str) -> list[str]:
    """
    Devuelve hasta 10 nombres de equipo de API-Football que coincidan con `query`.
    Usado por el endpoint de autocomplete de zonas fan.
    """
    if not query or len(query) < 1:
        return []
    if not settings.API_FOOTBALL_KEY:
        return []
    try:
        r = requests.get(
            f"{API_FOOTBALL_BASE}/teams",
            headers=API_FOOTBALL_HEADERS,
            params={"search": query},
            timeout=8,
        )
        r.raise_for_status()
        equipos = r.json().get("response", [])
        return [e["team"]["name"] for e in equipos if e.get("team", {}).get("name")][:10]
    except Exception:
        return []