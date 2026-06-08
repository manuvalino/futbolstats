"""
plantilla/services.py
F3 — Valor de mercado de la plantilla usando API-Football v3 + Pandas.

Cambio crítico (diagnóstico):
  /players/squads requiere plan de pago → devuelve vacío en free tier.
  Solución: usar GET /players?team={id}&season={season} que sí funciona
  en el tier gratuito. Este endpoint pagina de 20 en 20; recogemos todas
  las páginas automáticamente.

  IDs de jugador en /players y en /transfers son los mismos → el cruce
  funciona correctamente una vez usamos el endpoint correcto.

Flujo:
  1. GET /players?team={id}&season={season}  → plantilla completa (paginado)
  2. GET /transfers?team={id}                → fees de transferencia
  3. Cruce por player.id → valor real o fallback por posición
"""

import requests
import pandas as pd
import unicodedata
from django.conf import settings

API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
CURRENT_SEASON    = 2024   # temporada a consultar


def normalizar_nombre_equipo(texto: str) -> str:
    """Normaliza un nombre para comparar equipos de forma robusta."""
    texto = (texto or "").strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return " ".join(texto.split())


def elegir_candidato_por_nombre(candidatos: list[dict], nombre_buscado: str) -> dict | None:
    """
    Si existe una coincidencia exacta por nombre (ignorando mayúsculas y acentos),
    devuelve ese equipo para evitar que el usuario tenga que elegir manualmente.
    """
    if not candidatos:
        return None

    nombre_normalizado = normalizar_nombre_equipo(nombre_buscado)
    if not nombre_normalizado:
        return None

    exactos = [
        c for c in candidatos
        if normalizar_nombre_equipo(c.get("nombre", "")) == nombre_normalizado
    ]
    if exactos:
        return exactos[0]
    return None


def _headers() -> dict:
    return {"x-apisports-key": settings.API_FOOTBALL_KEY}


# ── Fallback por posición (cuando no hay fee registrado) ─────────────────────
VALOR_FALLBACK = {
    "Goalkeeper": 2_000_000,
    "Defender":   5_000_000,
    "Midfielder": 8_000_000,
    "Attacker":   7_000_000,
}

POSICION_ES = {
    "Goalkeeper": "Portero",
    "Defender":   "Defensa",
    "Midfielder": "Centrocampista",
    "Attacker":   "Delantero",
}


def _parsear_fee(fee_str: str | None) -> float | None:
    """
    Convierte strings de la API como '€45M', '£12.5M', '$3K', 'Free'
    a float en euros. Devuelve None para Free/Loan/vacío.
    """
    if not fee_str:
        return None
    fee_str = fee_str.strip()
    if fee_str.lower() in ("free", "loan", "-", "n/a", ""):
        return None

    # Tipo de cambio aproximado para normalizar a euros
    fx = 1.0
    if fee_str.startswith("£"):
        fx = 1.17
        fee_str = fee_str[1:]
    elif fee_str.startswith("$"):
        fx = 0.92
        fee_str = fee_str[1:]
    elif fee_str.startswith("€"):
        fee_str = fee_str[1:]

    mult = 1.0
    if fee_str.upper().endswith("M"):
        mult = 1_000_000
        fee_str = fee_str[:-1]
    elif fee_str.upper().endswith("K"):
        mult = 1_000
        fee_str = fee_str[:-1]

    try:
        return float(fee_str) * mult * fx
    except ValueError:
        return None


# ── Búsqueda y metadatos de equipo ───────────────────────────────────────────

def buscar_equipos(nombre: str) -> list[dict]:
    """GET /teams?search={nombre} → lista de candidatos."""
    try:
        r = requests.get(
            f"{API_FOOTBALL_BASE}/teams",
            headers=_headers(),
            params={"search": nombre},
            timeout=10,
        )
        r.raise_for_status()
        payload = r.json()
        errores_api = payload.get("errors") or {}
        if errores_api:
            msg_error = " ".join(str(v) for v in errores_api.values()).strip()
            msg_error_lc = msg_error.lower()
            if "request limit" in msg_error_lc or "reached the request limit" in msg_error_lc:
                raise RuntimeError(
                    "No se puede completar la búsqueda porque API-Football "
                    "ha alcanzado el límite diario de peticiones."
                )
            raise RuntimeError(f"API-Football devolvió un error: {msg_error}")

        items = payload.get("response", [])
    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code if e.response else "desconocido"
        if codigo == 401:
            raise RuntimeError("Clave de API-Football inválida (HTTP 401).")
        raise RuntimeError(f"Error de API-Football al buscar equipos (HTTP {codigo}).")
    except requests.exceptions.Timeout:
        raise RuntimeError("La búsqueda tardó demasiado. Inténtalo de nuevo.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"No se pudo conectar con API-Football: {e}")

    return [
        {
            "id":     str(item["team"]["id"]),
            "nombre": item["team"]["name"],
            "pais":   item["team"].get("country", ""),
            "logo":   item["team"].get("logo", ""),
        }
        for item in items
        if item.get("team", {}).get("id")
    ]


def obtener_info_equipo(team_id: str) -> dict:
    """GET /teams?id={team_id} → metadatos del equipo."""
    try:
        r = requests.get(
            f"{API_FOOTBALL_BASE}/teams",
            headers=_headers(),
            params={"id": team_id},
            timeout=8,
        )
        r.raise_for_status()
        items = r.json().get("response", [])
        if not items:
            return {}
        t = items[0]["team"]
        return {
            "id":     str(t["id"]),
            "nombre": t["name"],
            "pais":   t.get("country", ""),
            "logo":   t.get("logo", ""),
        }
    except Exception:
        return {}


def obtener_plantilla(team_id: str, season: int = CURRENT_SEASON) -> list[dict]:
    """
    GET /players?team={id}&season={season}  — FUNCIONA en tier gratuito.
    Pagina automáticamente (20 jugadores/página) hasta recoger todos.

    Cada jugador devuelto incluye:
      player.id, player.name, player.age, player.photo,
      statistics[0].games.position  → Goalkeeper/Defender/Midfielder/Attacker
      statistics[0].games.number    → dorsal
    """
    jugadores: list[dict] = []
    page = 1

    while True:
        try:
            r = requests.get(
                f"{API_FOOTBALL_BASE}/players",
                headers=_headers(),
                params={"team": team_id, "season": season, "page": page},
                timeout=12,
            )
            r.raise_for_status()
            data = r.json()
        except requests.exceptions.HTTPError as e:
            codigo = e.response.status_code if e.response else "?"
            raise RuntimeError(f"Error al obtener plantilla (HTTP {codigo}).")
        except requests.exceptions.Timeout:
            raise RuntimeError("La descarga de la plantilla tardó demasiado.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"No se pudo conectar con API-Football: {e}")

        items = data.get("response", [])
        if not items:
            # Si la temporada actual no tiene datos, reintentamos con la anterior
            if page == 1 and season == CURRENT_SEASON:
                return obtener_plantilla(team_id, season=CURRENT_SEASON - 1)
            break

        for entry in items:
            p     = entry.get("player", {})
            stats = entry.get("statistics", [{}])
            stat  = stats[0] if stats else {}
            jugadores.append({
                "id":       str(p.get("id", "")),
                "nombre":   p.get("name", "Desconocido"),
                "edad":     p.get("age"),
                "foto":     p.get("photo", ""),
                "numero":   stat.get("games", {}).get("number"),
                "posicion": stat.get("games", {}).get("position") or "Midfielder",
            })

        paging = data.get("paging", {})
        if page >= paging.get("total", 1):
            break
        page += 1

    return jugadores


def obtener_fees_transferencias(team_id: str) -> dict[str, float]:
    """
    GET /transfers?team={team_id}
    Devuelve {player_id_str: fee_euros} con el fee más reciente
    de la transferencia de ENTRADA al equipo para cada jugador.
    Si no hay fee de entrada, usa el más reciente de cualquier tipo.
    Falla silenciosamente (devuelve {}) para no bloquear la vista.

    Estructura real confirmada por diagnóstico:
      response[i].player.id
      response[i].transfers[j].date
      response[i].transfers[j].type   ← "Free", "Loan", fee string o None
      response[i].transfers[j].teams.in.id / .out.id
    """
    try:
        r = requests.get(
            f"{API_FOOTBALL_BASE}/transfers",
            headers=_headers(),
            params={"team": team_id},
            timeout=12,
        )
        r.raise_for_status()
        items = r.json().get("response", [])
    except Exception:
        return {}

    fees: dict[str, float] = {}
    team_id_int = int(team_id)

    for entry in items:
        player_id = str(entry.get("player", {}).get("id", ""))
        if not player_id:
            continue

        transferencias = sorted(
            entry.get("transfers", []),
            key=lambda t: t.get("date", ""),
            reverse=True,
        )

        fee_encontrado = None

        # El campo del fee confirmado por diagnóstico es "type"
        # Puede contener "Free", "Loan", o un string de precio ("€5M", etc.)
        # Primero buscamos transferencias de ENTRADA al equipo con fee
        for t in transferencias:
            equipo_in = (t.get("teams", {}).get("in") or {}).get("id")
            if equipo_in == team_id_int:
                fee = _parsear_fee(t.get("type"))
                if fee is not None:
                    fee_encontrado = fee
                    break

        # Si no hay fee de entrada, tomamos el más reciente con fee de cualquier tipo
        if fee_encontrado is None:
            for t in transferencias:
                fee = _parsear_fee(t.get("type"))
                if fee is not None:
                    fee_encontrado = fee
                    break

        if fee_encontrado is not None:
            fees[player_id] = fee_encontrado

    return fees


# ── Análisis con Pandas ─────────────────────────────────────────

def analizar_valor_plantilla(jugadores: list[dict], fees: dict[str, float]) -> dict:
    """
    Cruza plantilla con fees de transferencia por player.id.
    - fee real disponible   → valor_euros = fee,      fuente = 'Transferencia'
    - sin fee               → valor_euros = fallback,  fuente = 'Estimado'
    Aplica groupby + agg con Pandas.
    """
    if not jugadores:
        return {"error": "No se encontraron jugadores para este equipo."}

    filas = []
    for j in jugadores:
        pos_api  = j.get("posicion", "Midfielder") or "Midfielder"
        pos_norm = pos_api if pos_api in VALOR_FALLBACK else "Midfielder"

        fee_real = fees.get(j["id"])
        valor    = fee_real if fee_real is not None else float(VALOR_FALLBACK[pos_norm])
        fuente   = "Transferencia" if fee_real is not None else "Estimado"

        filas.append({
            "id":          j["id"],
            "nombre":      j["nombre"],
            "numero":      j.get("numero"),
            "edad":        j.get("edad"),
            "foto":        j.get("foto", ""),
            "posicion":    pos_norm,
            "posicion_es": POSICION_ES.get(pos_norm, pos_norm),
            "valor_euros": valor,
            "fuente":      fuente,
        })

    df = pd.DataFrame(filas)

    resumen = (
        df.groupby("posicion_es")
        .agg(
            jugadores=("nombre", "count"),
            valor_total=("valor_euros", "sum"),
            valor_medio=("valor_euros", "mean"),
            con_fee_real=("fuente", lambda s: (s == "Transferencia").sum()),
        )
        .round(0)
        .sort_values("valor_total", ascending=False)
        .reset_index()
        .to_dict(orient="records")
    )

    tabla = (
        df.sort_values(["posicion_es", "valor_euros"], ascending=[True, False])
        .to_dict(orient="records")
    )

    return {
        "resumen":           resumen,
        "tabla":             tabla,
        "total_plantilla":   df["valor_euros"].sum(),
        "num_jugadores":     len(df),
        "jugadores_con_fee": int((df["fuente"] == "Transferencia").sum()),
    }