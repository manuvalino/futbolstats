import requests
import pandas as pd
import unicodedata
from django.conf import settings


def _normalizar_nombre(texto: str) -> str:
    texto = (texto or "").strip().lower()
    texto = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c)
    )
    return " ".join(texto.split())


def buscar_equipos(nombre: str) -> list[dict]:
    """
    Busca equipos en football-data.org y devuelve candidatos para autocomplete.
    """
    q_norm = _normalizar_nombre(nombre)
    if not q_norm:
        return []

    candidatos: list[dict] = []
    # Catálogo de football-data y filtrado local por texto
    url_api = "https://api.football-data.org/v4/teams"
    cabeceras = {"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY}
    try:
        resp = requests.get(
            url_api,
            headers=cabeceras,
            params={"limit": 500},
            timeout=10,
        )
        resp.raise_for_status()
        equipos = resp.json().get("teams", [])
    except requests.exceptions.Timeout:
        raise RuntimeError("La búsqueda de equipos tardó demasiado. Inténtalo de nuevo.")
    except requests.exceptions.HTTPError as e:
        codigo_resp = e.response.status_code if e.response is not None else "desconocido"
        if codigo_resp == 429:
            raise RuntimeError("No se puede buscar equipos: se alcanzó el límite de peticiones de la API.")
        raise RuntimeError(f"Error de la API football-data.org al buscar equipos (HTTP {codigo_resp})")
    except requests.exceptions.RequestException:
        raise RuntimeError("No se pudo conectar con la API football-data.org. Compruebe su conexión")

    ids_vistos = set()
    for eq in equipos:
        team_id = eq.get("id")
        team_name = eq.get("name", "")
        if not team_id or not team_name:
            continue
        if q_norm not in _normalizar_nombre(team_name):
            continue
        team_id_str = str(team_id)
        if team_id_str in ids_vistos:
            continue
        candidatos.append(
            {
                "id": team_id_str,
                "nombre": team_name,
                "logo": eq.get("crest", ""),
                "pais": (eq.get("area") or {}).get("name", ""),
            }
        )
        ids_vistos.add(team_id_str)

    return candidatos


def elegir_candidato_por_nombre(candidatos: list[dict], nombre_buscado: str) -> dict | None:
    """
    Elige automáticamente coincidencia exacta ignorando acentos y mayúsculas.
    """
    buscado = _normalizar_nombre(nombre_buscado)
    if not buscado:
        return None
    exactos = [c for c in candidatos if _normalizar_nombre(c["nombre"]) == buscado]
    return exactos[0] if exactos else None

def get_partidos_equipo(equipo_id, n_partidos):
    url_API = f"http://api.football-data.org/v4/teams/{equipo_id}/matches"
    cabeceras = {"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY}
    params = {"status": "FINISHED", "limit": n_partidos}

    try:
        resp = requests.get(url_API, headers=cabeceras, params=params)
        resp.raise_for_status()
        datos_encontrados = resp.json()
        partidos_encontrados = datos_encontrados.get("matches", [])
        return partidos_encontrados
    except requests.exceptions.Timeout:
        raise RuntimeError("La API tardó mucho en responder. Inténtelo de nuevo")
    except requests.exceptions.HTTPError as e:
        codigo_resp = e.response.status_code if e.response is not None else "desconocido"
        if codigo_resp in (400, 404, "desconocido"):
            raise RuntimeError(
                "Lo siento, dicho equipo no está registrado en nuestra API. "
                "Comprueba el nombre e inténtalo de nuevo."
            )
        if codigo_resp == 429:
            raise RuntimeError(
                "No se puede completar la consulta porque se alcanzó el límite de peticiones de la API."
            )
        raise RuntimeError(f"Error de la API football-data.org (HTTP {codigo_resp})")
    except requests.exceptions.RequestException:
        raise RuntimeError("No se pudo conectar con la API football-data.org. Compruebe su conexión")


def procesar_rendimiento(partidos_encontrados, equipo_id):
    if not partidos_encontrados:
        return {}
    
    dataFrame = pd.json_normalize(partidos_encontrados)

    dataFrame['Es_Local'] = dataFrame['homeTeam.id'] == int(equipo_id)
    dataFrame['Condicion'] = dataFrame['Es_Local'].map({True: 'Local', False: 'Visitante'})

    dataFrame['Goles_Favor'] = dataFrame.apply(lambda row: row['score.fullTime.home'] if row['Es_Local'] else row['score.fullTime.away'], axis=1)
    dataFrame['Goles_Contra'] = dataFrame.apply(lambda row: row['score.fullTime.away'] if row['Es_Local'] else row['score.fullTime.home'], axis=1)
    dataFrame['Diferencia_Goles'] = dataFrame['Goles_Favor'] - dataFrame['Goles_Contra']
    
    media = dataFrame.groupby('Condicion')[['Goles_Favor', 'Goles_Contra', 'Diferencia_Goles']].mean().round(3)


    dataFrame['utcDate'] = dataFrame['utcDate'].str[:10]
    columnas_api = ['utcDate', 'homeTeam.name', 'score.fullTime.home', 'score.fullTime.away', 'awayTeam.name']
    nombres_finales = {
        'utcDate': 'Fecha',
        'homeTeam.name': 'Equipo_Local',
        'score.fullTime.home': 'Resultado_Local',
        'score.fullTime.away': 'Resultado_Visitante',
        'awayTeam.name': 'Equipo_Visitante'
    }

    lista_partidos = {}

    for i, j in dataFrame.groupby('Condicion'):
        lista_partidos[i] = j[columnas_api].rename(columns=nombres_finales).to_dict('records')

    
    return {
        'medias': media.to_dict('index'),
        'lista_partidos': lista_partidos
    }
