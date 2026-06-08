"""
hemeroteca/tests.py
===================
F5 — Hemeroteca y resúmenes en vídeo (YouTube Data API v3).

Estructura
----------
  ConstruirQueryTests           — construir_query (lógica pura)
  BuscarVideosYoutubeTests      — buscar_videos_youtube con @patch (API + Pandas)
  BuscarVideosYoutubeExtraTests — casos adicionales API/Pandas/HTTP
  HemerotecaViewTests           — vista principal (login, GET, POST)
  HemerotecaViewExtraTests      — ramas extra de la vista POST
  AutocompleteHemerotecaTests   — endpoint JSON de sugerencias locales
  AutocompleteHemerotecaExtraTests — límites y formato JSON
"""

from unittest.mock import patch, MagicMock

import requests as _requests_module

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from hemeroteca.services import (
    YOUTUBE_SEARCH_URL,
    buscar_videos_youtube,
    construir_query,
)
from hemeroteca.views import SUGERENCIAS_HEMEROTECA


# ──────────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ──────────────────────────────────────────────────────────────────────────────

YOUTUBE_API_KEY_TEST = "test-youtube-key"


def _mock_response_ok(json_payload, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.raise_for_status = MagicMock()
    m.json.return_value = json_payload
    return m


def _item_youtube(
    video_id="dQw4w9WgXcQ",
    titulo="Resumen Deportivo vs Milan",
    canal="Canal Fútbol",
    published_at="2004-04-07T20:00:00Z",
    thumb_high="https://i.ytimg.com/vi/high.jpg",
    thumb_medium="https://i.ytimg.com/vi/med.jpg",
    thumb_default="https://i.ytimg.com/vi/default.jpg",
):
    return {
        "id": {"videoId": video_id},
        "snippet": {
            "title": titulo,
            "channelTitle": canal,
            "publishedAt": published_at,
            "thumbnails": {
                "high": {"url": thumb_high},
                "medium": {"url": thumb_medium},
                "default": {"url": thumb_default},
            },
        },
    }


def _payload_youtube(items=None):
    return {"items": items if items is not None else [_item_youtube()]}


# ──────────────────────────────────────────────────────────────────────────────
# 1. construir_query
# ──────────────────────────────────────────────────────────────────────────────

class ConstruirQueryTests(TestCase):
    """Valida la construcción de la query de búsqueda para YouTube."""

    def test_texto_vacio_devuelve_query_por_defecto(self):
        self.assertEqual(
            construir_query(""),
            "RC Deportivo de La Coruña resumen goles",
        )
        self.assertEqual(
            construir_query("   "),
            "RC Deportivo de La Coruña resumen goles",
        )

    def test_texto_simple_anade_resumen_partido(self):
        q = construir_query("Celta de Vigo")
        self.assertEqual(q, "Celta de Vigo resumen partido goles")

    def test_texto_con_ano_usa_highlights(self):
        q = construir_query("Deportivo Milan 2004")
        self.assertEqual(q, "Deportivo Milan 2004 resumen goles highlights")

    def test_texto_con_guion_largo_usa_highlights(self):
        q = construir_query("Deportivo 4 – 0 Milan")
        self.assertIn("highlights", q)
        self.assertIn("Deportivo 4 – 0 Milan", q)

    def test_texto_con_guion_espacio_usa_highlights(self):
        q = construir_query("Deportivo 4 - 0 Milan")
        self.assertIn("highlights", q)

    def test_texto_con_vs_usa_highlights(self):
        q = construir_query("Deportivo vs Real Madrid")
        self.assertEqual(
            q,
            "Deportivo vs Real Madrid resumen goles highlights",
        )

    def test_texto_con_VS_mayusculas(self):
        q = construir_query("Deportivo VS Barcelona")
        self.assertIn("highlights", q)

    def test_strip_espacios_laterales(self):
        q = construir_query("  Real Madrid  ")
        self.assertTrue(q.startswith("Real Madrid"))

    def test_ano_y_vs_combinados_usan_highlights(self):
        q = construir_query("Deportivo vs Milan 2004")
        self.assertIn("highlights", q)
        self.assertIn("Deportivo vs Milan 2004", q)

    def test_ano_1990_dispara_highlights(self):
        q = construir_query("Gol histórico 1990")
        self.assertIn("highlights", q)

    def test_ano_2029_dispara_highlights(self):
        q = construir_query("Final 2029")
        self.assertIn("highlights", q)

    def test_ano_1989_no_dispara_solo_por_ano(self):
        q = construir_query("Copa 1989")
        self.assertIn("resumen partido goles", q)
        self.assertNotIn("highlights", q)

    def test_guion_sin_espacios_no_es_partido_formal(self):
        q = construir_query("Deportivo-Milan")
        self.assertIn("resumen partido goles", q)

    def test_preserva_texto_original_en_query(self):
        texto = "RC Celta de Vigo"
        q = construir_query(texto)
        self.assertTrue(q.startswith(texto))


# ──────────────────────────────────────────────────────────────────────────────
# 2. buscar_videos_youtube
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(YOUTUBE_API_KEY=YOUTUBE_API_KEY_TEST)
class BuscarVideosYoutubeTests(TestCase):
    """Valida buscar_videos_youtube mockeando requests.get."""

    @override_settings(YOUTUBE_API_KEY=None)
    def test_sin_api_key_lanza_runtime(self):
        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("YouTube", str(ctx.exception))

    @override_settings(YOUTUBE_API_KEY="")
    def test_api_key_vacia_lanza_runtime(self):
        with self.assertRaises(RuntimeError):
            buscar_videos_youtube("test")

    @patch("hemeroteca.services.requests.get")
    def test_busqueda_exitosa_devuelve_lista_dicts(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        videos = buscar_videos_youtube("Deportivo resumen", max_results=5)

        self.assertEqual(len(videos), 1)
        v = videos[0]
        self.assertEqual(v["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(v["titulo"], "Resumen Deportivo vs Milan")
        self.assertEqual(v["canal"], "Canal Fútbol")
        self.assertEqual(v["publicado"], "2004-04-07")
        self.assertIn("youtube.com/embed/dQw4w9WgXcQ", v["embed_url"])
        self.assertIn("watch?v=dQw4w9WgXcQ", v["watch_url"])

    @patch("hemeroteca.services.requests.get")
    def test_items_vacios_devuelve_lista_vacia(self, mock_get):
        mock_get.return_value = _mock_response_ok({"items": []})
        self.assertEqual(buscar_videos_youtube("xyz"), [])

    @patch("hemeroteca.services.requests.get")
    def test_sin_video_id_en_columnas_devuelve_vacio(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "items": [{"id": {}, "snippet": {"title": "Sin id"}}],
        })
        self.assertEqual(buscar_videos_youtube("test"), [])

    @patch("hemeroteca.services.requests.get")
    def test_varios_videos(self, mock_get):
        items = [
            _item_youtube("aaa", "Video A", "Canal A"),
            _item_youtube("bbb", "Video B", "Canal B"),
        ]
        mock_get.return_value = _mock_response_ok(_payload_youtube(items))
        videos = buscar_videos_youtube("query", max_results=10)
        self.assertEqual(len(videos), 2)
        ids = {v["video_id"] for v in videos}
        self.assertEqual(ids, {"aaa", "bbb"})

    @patch("hemeroteca.services.requests.get")
    def test_thumbnail_usa_high_si_existe(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        videos = buscar_videos_youtube("q")
        self.assertEqual(videos[0]["thumbnail"], "https://i.ytimg.com/vi/high.jpg")

    @patch("hemeroteca.services.requests.get")
    def test_pasa_max_results_en_params(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        buscar_videos_youtube("query test", max_results=3)
        params = mock_get.call_args[1]["params"]
        self.assertEqual(params["maxResults"], 3)
        self.assertEqual(params["q"], "query test")
        self.assertEqual(params["type"], "video")
        self.assertEqual(params["key"], YOUTUBE_API_KEY_TEST)

    @patch("hemeroteca.services.requests.get")
    def test_http_403_lanza_runtime_con_mensaje_claro(self, mock_get):
        resp = MagicMock()
        resp.status_code = 403
        http_error = _requests_module.exceptions.HTTPError(response=resp)
        m = MagicMock()
        m.raise_for_status.side_effect = http_error
        mock_get.return_value = m

        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("403", str(ctx.exception))
        self.assertIn("denegado", str(ctx.exception).lower())

    @patch("hemeroteca.services.requests.get")
    def test_http_500_lanza_runtime(self, mock_get):
        resp = MagicMock()
        resp.status_code = 500
        http_error = _requests_module.exceptions.HTTPError(response=resp)
        m = MagicMock()
        m.raise_for_status.side_effect = http_error
        mock_get.return_value = m

        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("500", str(ctx.exception))

    @patch("hemeroteca.services.requests.get")
    def test_http_error_sin_response(self, mock_get):
        http_error = _requests_module.exceptions.HTTPError()
        m = MagicMock()
        m.raise_for_status.side_effect = http_error
        mock_get.return_value = m

        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("?", str(ctx.exception))

    @patch("hemeroteca.services.requests.get")
    def test_timeout_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("tardó demasiado", str(ctx.exception))

    @patch("hemeroteca.services.requests.get")
    def test_connection_error_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError("refused")
        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("test")
        self.assertIn("conectar", str(ctx.exception).lower())


@override_settings(YOUTUBE_API_KEY=YOUTUBE_API_KEY_TEST)
class BuscarVideosYoutubeExtraTests(TestCase):
    """Casos adicionales: HTTP, thumbnails, Pandas y forma del resultado."""

    @patch("hemeroteca.services.requests.get")
    def test_embed_url_contiene_parametros_iframe(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        embed = buscar_videos_youtube("q")[0]["embed_url"]
        self.assertIn("rel=0", embed)
        self.assertIn("modestbranding=1", embed)
        self.assertIn("controls=1", embed)
        self.assertIn("enablejsapi=1", embed)

    @patch("hemeroteca.services.requests.get")
    def test_llamada_usa_url_oficial_y_timeout(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        buscar_videos_youtube("consulta")
        mock_get.assert_called_once()
        self.assertEqual(mock_get.call_args[0][0], YOUTUBE_SEARCH_URL)
        self.assertEqual(mock_get.call_args[1]["timeout"], 10)

    @patch("hemeroteca.services.requests.get")
    def test_json_sin_clave_items_devuelve_vacio(self, mock_get):
        mock_get.return_value = _mock_response_ok({})
        self.assertEqual(buscar_videos_youtube("q"), [])

    @patch("hemeroteca.services.requests.get")
    def test_video_id_valido_presente_aunque_haya_nulos(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "items": [
                _item_youtube("valido"),
                {"id": {"videoId": None}, "snippet": _item_youtube()["snippet"]},
            ],
        })
        videos = buscar_videos_youtube("q")
        ids = [v.get("video_id") for v in videos]
        self.assertIn("valido", ids)

    @patch("hemeroteca.services.requests.get")
    def test_claves_finales_del_dict(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        v = buscar_videos_youtube("q")[0]
        for clave in (
            "video_id", "titulo", "thumbnail", "canal",
            "publicado", "embed_url", "watch_url",
        ):
            with self.subTest(clave=clave):
                self.assertIn(clave, v)

    @patch("hemeroteca.services.requests.get")
    def test_http_401_lanza_runtime_generico(self, mock_get):
        resp = MagicMock()
        resp.status_code = 401
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("q")
        self.assertIn("401", str(ctx.exception))

    @patch("hemeroteca.services.requests.get")
    def test_http_404_lanza_runtime_generico(self, mock_get):
        resp = MagicMock()
        resp.status_code = 404
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            buscar_videos_youtube("q")
        self.assertIn("404", str(ctx.exception))

    @patch("hemeroteca.services.requests.get")
    def test_max_results_por_defecto_es_8(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        buscar_videos_youtube("q")
        self.assertEqual(mock_get.call_args[1]["params"]["maxResults"], 8)

    @patch("hemeroteca.services.requests.get")
    def test_publicado_solo_fecha_sin_hora(self, mock_get):
        item = _item_youtube(published_at="2023-12-25T18:30:00Z")
        mock_get.return_value = _mock_response_ok(_payload_youtube([item]))
        self.assertEqual(buscar_videos_youtube("q")[0]["publicado"], "2023-12-25")

    @patch("hemeroteca.services.requests.get")
    def test_tipos_salida_str_en_campos_texto(self, mock_get):
        mock_get.return_value = _mock_response_ok(_payload_youtube())
        v = buscar_videos_youtube("q")[0]
        self.assertIsInstance(v["titulo"], str)
        self.assertIsInstance(v["canal"], str)
        self.assertIsInstance(v["embed_url"], str)

    @patch("hemeroteca.services.requests.get")
    def test_mezacla_item_valido_siempre_en_resultado(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "items": [
                {"id": {}, "snippet": {"title": "Mal"}},
                _item_youtube("ok1"),
            ],
        })
        videos = buscar_videos_youtube("q")
        self.assertTrue(any(v.get("video_id") == "ok1" for v in videos))

    @patch("hemeroteca.services.requests.get")
    def test_raise_for_status_se_invoca(self, mock_get):
        m = _mock_response_ok(_payload_youtube())
        mock_get.return_value = m
        buscar_videos_youtube("q")
        m.raise_for_status.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# 3. Vista hemeroteca
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class HemerotecaViewTests(TestCase):
    """Tests HTTP de la vista principal F5."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="hemuser", password="testpass")
        self.url = reverse("hemeroteca:hemeroteca")

    def test_get_sin_login_redirige(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_sin_login_redirige(self):
        response = self.client.post(self.url, {"busqueda": "Deportivo"})
        self.assertEqual(response.status_code, 302)

    def test_get_autenticado_renderiza_template(self):
        self.client.login(username="hemuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "hemeroteca/hemeroteca.html")
        self.assertIsNone(response.context["videos"])
        self.assertIn("sugerencias", response.context)

    def test_post_sin_busqueda_muestra_error(self):
        self.client.login(username="hemuser", password="testpass")
        response = self.client.post(self.url, {"busqueda": ""})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Introduce" in m for m in msgs))

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query", return_value="query construida")
    def test_post_exitoso_muestra_videos(self, mock_query, mock_buscar):
        mock_buscar.return_value = [
            {
                "video_id": "abc",
                "titulo": "Resumen",
                "canal": "Canal",
                "publicado": "2020-01-01",
                "thumbnail": "https://thumb.jpg",
                "embed_url": "https://www.youtube.com/embed/abc",
                "watch_url": "https://www.youtube.com/watch?v=abc",
            }
        ]
        self.client.login(username="hemuser", password="testpass")
        response = self.client.post(self.url, {"busqueda": "Deportivo 2004"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["videos"]), 1)
        self.assertEqual(response.context["query_usada"], "Deportivo 2004")
        mock_query.assert_called_once_with("Deportivo 2004")
        mock_buscar.assert_called_once_with("query construida", max_results=9)

    @patch("hemeroteca.views.buscar_videos_youtube", return_value=[])
    @patch("hemeroteca.views.construir_query", return_value="q")
    def test_post_sin_videos_muestra_info(self, mock_query, mock_buscar):
        self.client.login(username="hemuser", password="testpass")
        response = self.client.post(self.url, {"busqueda": "xyz inexistente"})
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("No se encontraron vídeos" in m for m in msgs))

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query", return_value="q")
    def test_post_runtime_error_muestra_error(self, mock_query, mock_buscar):
        mock_buscar.side_effect = RuntimeError("Acceso denegado por la YouTube API (HTTP 403).")
        self.client.login(username="hemuser", password="testpass")
        response = self.client.post(self.url, {"busqueda": "Deportivo"})
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("403" in m or "denegado" in m for m in msgs))


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class HemerotecaViewExtraTests(TestCase):
    """Ramas adicionales de la vista hemeroteca."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="hemextra", password="testpass")
        self.url = reverse("hemeroteca:hemeroteca")

    def test_post_solo_espacios_muestra_error(self):
        self.client.login(username="hemextra", password="testpass")
        response = self.client.post(self.url, {"busqueda": "     "})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Introduce" in m for m in msgs))
        self.assertIsNone(response.context["videos"])

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query", return_value="q")
    def test_post_error_videos_sigue_none(self, mock_query, mock_buscar):
        mock_buscar.side_effect = RuntimeError("Error de conexión con la YouTube API")
        self.client.login(username="hemextra", password="testpass")
        response = self.client.post(self.url, {"busqueda": "Celta"})
        self.assertIsNone(response.context["videos"])

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query", return_value="q")
    def test_post_error_query_usada_igualmente(self, mock_query, mock_buscar):
        mock_buscar.side_effect = RuntimeError("fallo")
        self.client.login(username="hemextra", password="testpass")
        response = self.client.post(self.url, {"busqueda": "  Betis  "})
        self.assertEqual(response.context["query_usada"], "Betis")

    def test_get_incluye_lista_sugerencias(self):
        self.client.login(username="hemextra", password="testpass")
        response = self.client.get(self.url)
        sugerencias = response.context["sugerencias"]
        self.assertGreater(len(sugerencias), 0)
        self.assertIn("RC Deportivo de La Coruña", sugerencias)

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query", return_value="q yt")
    def test_post_sin_videos_lista_vacia_en_contexto(self, mock_query, mock_buscar):
        mock_buscar.return_value = []
        self.client.login(username="hemextra", password="testpass")
        response = self.client.post(self.url, {"busqueda": "xyz"})
        self.assertEqual(response.context["videos"], [])

    @patch("hemeroteca.views.buscar_videos_youtube")
    @patch("hemeroteca.views.construir_query")
    def test_post_llama_construir_query_antes_de_api(self, mock_query, mock_buscar):
        mock_query.return_value = "query final"
        mock_buscar.return_value = []
        self.client.login(username="hemextra", password="testpass")
        self.client.post(self.url, {"busqueda": "Milan"})
        mock_query.assert_called_once_with("Milan")
        mock_buscar.assert_called_once_with("query final", max_results=9)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Vista autocomplete_hemeroteca
# ──────────────────────────────────────────────────────────────────────────────

class AutocompleteHemerotecaTests(TestCase):
    """Autocomplete local (sin API): filtra SUGERENCIAS_HEMEROTECA."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="hemauto", password="testpass")
        self.url = reverse("hemeroteca:autocomplete")

    def test_sin_login_redirige(self):
        response = self.client.get(self.url, {"q": "dep"})
        self.assertEqual(response.status_code, 302)

    def test_query_un_caracter_devuelve_vacio(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": "d"})
        self.assertEqual(response.json()["sugerencias"], [])

    def test_query_vacia_devuelve_vacio(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.json()["sugerencias"], [])

    def test_filtra_sugerencias_por_subcadena(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": "milan"})
        data = response.json()["sugerencias"]
        self.assertGreater(len(data), 0)
        for s in data:
            self.assertIn("milan", s.lower())

    def test_maximo_8_sugerencias(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": "deportivo"})
        self.assertLessEqual(len(response.json()["sugerencias"]), 8)

    def test_deportivo_devuelve_varias_coincidencias(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": "rc deportivo"})
        self.assertGreaterEqual(len(response.json()["sugerencias"]), 1)

    def test_sin_coincidencias_lista_vacia(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.get(self.url, {"q": "zzzznop existe"})
        self.assertEqual(response.json()["sugerencias"], [])

    def test_post_devuelve_405(self):
        self.client.login(username="hemauto", password="testpass")
        response = self.client.post(self.url, {"q": "dep"})
        self.assertEqual(response.status_code, 405)


class AutocompleteHemerotecaExtraTests(TestCase):
    """Casos límite del autocomplete local."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="hemauto2", password="testpass")
        self.url = reverse("hemeroteca:autocomplete")

    def test_query_exactamente_2_caracteres(self):
        self.client.login(username="hemauto2", password="testpass")
        response = self.client.get(self.url, {"q": "rc"})
        self.assertEqual(response.status_code, 200)
        self.assertGreater(len(response.json()["sugerencias"]), 0)

    def test_query_mayusculas_encuentra_coincidencias(self):
        self.client.login(username="hemauto2", password="testpass")
        response = self.client.get(self.url, {"q": "BARCELONA"})
        sugerencias = response.json()["sugerencias"]
        self.assertTrue(any("Barcelona" in s for s in sugerencias))

    def test_respuesta_json_tiene_clave_sugerencias(self):
        self.client.login(username="hemauto2", password="testpass")
        data = self.client.get(self.url, {"q": "real"}).json()
        self.assertIsInstance(data["sugerencias"], list)

    def test_resultados_son_cadenas_de_sugerencias_originales(self):
        self.client.login(username="hemauto2", password="testpass")
        sugerencias = self.client.get(self.url, {"q": "madrid"}).json()["sugerencias"]
        for s in sugerencias:
            self.assertIn(s, SUGERENCIAS_HEMEROTECA)

    def test_query_con_espacios_strip(self):
        self.client.login(username="hemauto2", password="testpass")
        response = self.client.get(self.url, {"q": "  milan  "})
        for s in response.json()["sugerencias"]:
            self.assertIn("milan", s.lower())

    def test_seleccion_espanola(self):
        self.client.login(username="hemauto2", password="testpass")
        sugerencias = self.client.get(self.url, {"q": "españ"}).json()["sugerencias"]
        self.assertIn("Selección española", sugerencias)

    def test_ac_milan_partido_historico(self):
        self.client.login(username="hemauto2", password="testpass")
        sugerencias = self.client.get(self.url, {"q": "milan 2004"}).json()["sugerencias"]
        self.assertTrue(any("Milan 2004" in s for s in sugerencias))

    def test_content_type_json(self):
        self.client.login(username="hemauto2", password="testpass")
        response = self.client.get(self.url, {"q": "celta"})
        self.assertEqual(response["Content-Type"], "application/json")
