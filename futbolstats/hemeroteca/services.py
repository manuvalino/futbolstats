"""
hemeroteca/services.py
F5 — Hemeroteca y resúmenes en vídeo (solo YouTube Data API v3).
Los vídeos se reproducen embebidos en la propia web mediante iframe.

"""


import requests
import pandas as pd
from django.conf import settings

YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

def buscar_videos_youtube(query: str, max_results: int = 8) -> list[dict]:
    
    api_key = getattr(settings, "YOUTUBE_API_KEY", None)
    if not api_key:
        raise RuntimeError(
            "Error de conexión con la YouTube API"
        )

    params = {
        "part":              "snippet",
        "q":                 query,
        "type":              "video",
        "maxResults":        max_results,
        "key":               api_key,
    }
    try:
        r = requests.get(YOUTUBE_SEARCH_URL, params=params, timeout=10)
        r.raise_for_status()
        items = r.json().get("items", [])

        if not items:
            return []
        
        df = pd.json_normalize(items)

        if 'id.videoId' not in df.columns:
            return []
        
        df['thumbnail'] = df.get('snippet.thumbnails.high.url', pd.Series(dtype=str))\
                          .fillna(df.get('snippet.thumbnails.medium.url'))\
                          .fillna(df.get('snippet.thumbnails.default.url', ''))
        
        df['publicado'] = df['snippet.publishedAt'].str[:10]
    
        df['embed_url'] = "https://www.youtube.com/embed/" + df['id.videoId'] + "?rel=0&modestbranding=1&controls=1&enablejsapi=1"
        df['watch_url'] = "https://www.youtube.com/watch?v=" + df["id.videoId"]

        columnas_api = ['id.videoId', 'snippet.title', 'thumbnail', 'snippet.channelTitle', 'publicado', 'embed_url', 'watch_url']
        nombres_finales = {
            'id.videoId': 'video_id',
            'snippet.title': 'titulo',
            'snippet.channelTitle': 'canal',
        }

        columnas_finales = [c for c in columnas_api if c in df.columns]
        df_final = df[columnas_finales].rename(columns=nombres_finales)
        return df_final.to_dict('records')

    except requests.exceptions.HTTPError as e:
        codigo = e.response.status_code if e.response else "?"
        if codigo == 403:
            raise RuntimeError(
                "Acceso denegado por la YouTube API (HTTP 403). "
                "Comprueba que la clave es válida y que la API está habilitada."
            )
        raise RuntimeError(f"Error de YouTube API (HTTP {codigo}).")
    except requests.exceptions.Timeout:
        raise RuntimeError("La búsqueda en YouTube tardó demasiado. Inténtalo de nuevo.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"No se pudo conectar con YouTube: {e}")


def construir_query(texto: str) -> str:
    texto = texto.strip()
    if not texto:
        return "RC Deportivo de La Coruña resumen goles"
    tiene_año   = any(str(y) in texto for y in range(1990, 2030))
    tiene_guion = " - " in texto or " – " in texto
    tiene_vs = "vs" in texto.lower()

    if (tiene_año or tiene_guion or tiene_vs):
        return f"{texto} resumen goles highlights"
    return f"{texto} resumen partido goles"