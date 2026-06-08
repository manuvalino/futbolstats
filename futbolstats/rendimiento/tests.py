"""
rendimiento/tests.py
====================
F1 — Análisis de rendimiento local vs. visitante (football-data.org + Pandas).

Estructura
----------
  NormalizacionTests              — _normalizar_nombre, elegir_candidato_por_nombre
  BuscarEquiposTests              — buscar_equipos mockeando football-data.org
  GetPartidosEquipoTests          — get_partidos_equipo mockeado
  ProcesarRendimientoTests        — procesar_rendimiento (Pandas) ← núcleo F1
  ConstruirDatosGraficaTests      — _construir_datos_grafica (lógica pura)
  DashboardViewTests              — vista dashboard
  IndexViewTests                  — vista index (GET, candidatos, errores)
  AutocompleteEquiposTests        — autocomplete JSON (sin login)
"""

from unittest.mock import patch, MagicMock

import requests as _requests_module

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from rendimiento.services import (
    _normalizar_nombre,
    buscar_equipos,
    elegir_candidato_por_nombre,
    get_partidos_equipo,
    procesar_rendimiento,
)
from rendimiento.views import _construir_datos_grafica


# ──────────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ──────────────────────────────────────────────────────────────────────────────

FOOTBALL_DATA_KEY_TEST = "test-football-data-key"
EQUIPO_ID = "558"


def _mock_response_ok(json_payload, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.raise_for_status = MagicMock()
    m.json.return_value = json_payload
    return m


def _equipo_api(team_id, name, country="Spain", crest="http://crest.png"):
    return {
        "id": team_id,
        "name": name,
        "crest": crest,
        "area": {"name": country},
    }


def _payload_teams(teams):
    return {"teams": teams}


CANDIDATOS_MUESTRA = [
    {"id": "558", "nombre": "RC Deportivo de La Coruña", "pais": "Spain", "logo": "http://d.png"},
    {"id": "86", "nombre": "Real Madrid CF", "pais": "Spain", "logo": ""},
    {"id": "735", "nombre": "Deportivo Alavés", "pais": "Spain", "logo": ""},
]


def _partido(
    fecha="2024-03-10T20:00:00Z",
    home_id=558,
    home_name="RC Deportivo",
    away_id=999,
    away_name="Rival FC",
    goles_home=2,
    goles_away=1,
):
    return {
        "utcDate": fecha,
        "homeTeam": {"id": home_id, "name": home_name},
        "awayTeam": {"id": away_id, "name": away_name},
        "score": {"fullTime": {"home": goles_home, "away": goles_away}},
    }


PARTIDO_LOCAL = _partido("2024-01-10T18:00:00Z", 558, "RC Deportivo", 100, "Rival A", 3, 0)
PARTIDO_VISITANTE = _partido("2024-02-15T18:00:00Z", 200, "Rival B", 558, "RC Deportivo", 1, 2)


# ──────────────────────────────────────────────────────────────────────────────
# 1. Normalización y elección de candidato
# ──────────────────────────────────────────────────────────────────────────────

class NormalizacionTests(TestCase):
    def test_normalizar_minusculas(self):
        self.assertEqual(_normalizar_nombre("RC Deportivo"), "rc deportivo")

    def test_normalizar_acentos(self):
        self.assertEqual(_normalizar_nombre("Atlético"), "atletico")

    def test_normalizar_espacios(self):
        self.assertEqual(_normalizar_nombre("  Real   Madrid  "), "real madrid")

    def test_normalizar_vacio_y_none(self):
        self.assertEqual(_normalizar_nombre(""), "")
        self.assertEqual(_normalizar_nombre(None), "")

    def test_elegir_exacto(self):
        r = elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, "RC Deportivo de La Coruña")
        self.assertEqual(r["id"], "558")

    def test_elegir_ignora_mayusculas_y_acentos(self):
        cands = [{"id": "1", "nombre": "Atlético de Madrid", "pais": "", "logo": ""}]
        r = elegir_candidato_por_nombre(cands, "atletico de madrid")
        self.assertEqual(r["id"], "1")

    def test_elegir_sin_coincidencia_none(self):
        self.assertIsNone(elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, "Manchester City"))

    def test_elegir_lista_vacia_none(self):
        self.assertIsNone(elegir_candidato_por_nombre([], "Deportivo"))

    def test_elegir_nombre_vacio_none(self):
        self.assertIsNone(elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, ""))


# ──────────────────────────────────────────────────────────────────────────────
# 2. buscar_equipos
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(FOOTBALL_DATA_API_KEY=FOOTBALL_DATA_KEY_TEST)
class BuscarEquiposTests(TestCase):
    @staticmethod
    def _teams_payload():
        return _payload_teams([
            _equipo_api(558, "RC Deportivo de La Coruña"),
            _equipo_api(86, "Real Madrid CF"),
            _equipo_api(735, "Deportivo Alavés"),
        ])

    def test_nombre_vacio_devuelve_lista_vacia(self):
        self.assertEqual(buscar_equipos(""), [])
        self.assertEqual(buscar_equipos("   "), [])

    @patch("rendimiento.services.requests.get")
    def test_filtra_por_subcadena(self, mock_get):
        mock_get.return_value = _mock_response_ok(self._teams_payload())
        resultado = buscar_equipos("Deportivo")
        nombres = {c["nombre"] for c in resultado}
        self.assertIn("RC Deportivo de La Coruña", nombres)
        self.assertIn("Deportivo Alavés", nombres)
        self.assertNotIn("Real Madrid CF", nombres)

    @patch("rendimiento.services.requests.get")
    def test_devuelve_campos_esperados(self, mock_get):
        mock_get.return_value = _mock_response_ok(self._teams_payload())
        c = buscar_equipos("Real Madrid")[0]
        for clave in ("id", "nombre", "logo", "pais"):
            with self.subTest(clave=clave):
                self.assertIn(clave, c)

    @patch("rendimiento.services.requests.get")
    def test_ignora_equipos_sin_id_o_nombre(self, mock_get):
        payload = _payload_teams([
            {"id": None, "name": "Sin ID"},
            {"id": 1, "name": ""},
            _equipo_api(558, "RC Deportivo"),
        ])
        mock_get.return_value = _mock_response_ok(payload)
        self.assertEqual(len(buscar_equipos("Deportivo")), 1)

    @patch("rendimiento.services.requests.get")
    def test_no_duplica_ids(self, mock_get):
        payload = _payload_teams([
            _equipo_api(558, "RC Deportivo"),
            _equipo_api(558, "RC Deportivo B"),
        ])
        mock_get.return_value = _mock_response_ok(payload)
        ids = [c["id"] for c in buscar_equipos("Deportivo")]
        self.assertEqual(ids.count("558"), 1)

    @patch("rendimiento.services.requests.get")
    def test_usa_token_y_limit_en_request(self, mock_get):
        mock_get.return_value = _mock_response_ok({"teams": []})
        buscar_equipos("x")
        headers = mock_get.call_args[1]["headers"]
        params = mock_get.call_args[1]["params"]
        self.assertEqual(headers["X-Auth-Token"], FOOTBALL_DATA_KEY_TEST)
        self.assertEqual(params["limit"], 500)
        self.assertEqual(mock_get.call_args[1]["timeout"], 10)

    @patch("rendimiento.services.requests.get")
    def test_timeout_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Dep")
        self.assertIn("tardó demasiado", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_http_429_lanza_runtime(self, mock_get):
        resp = MagicMock()
        resp.status_code = 429
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Dep")
        self.assertIn("límite", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_http_500_lanza_runtime(self, mock_get):
        resp = MagicMock()
        resp.status_code = 500
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Dep")
        self.assertIn("500", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_connection_error_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError()
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Dep")
        self.assertIn("conectar", str(ctx.exception).lower())


# ──────────────────────────────────────────────────────────────────────────────
# 3. get_partidos_equipo
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(FOOTBALL_DATA_API_KEY=FOOTBALL_DATA_KEY_TEST)
class GetPartidosEquipoTests(TestCase):
    @patch("rendimiento.services.requests.get")
    def test_devuelve_lista_matches(self, mock_get):
        partidos = [PARTIDO_LOCAL, PARTIDO_VISITANTE]
        mock_get.return_value = _mock_response_ok({"matches": partidos})
        resultado = get_partidos_equipo(EQUIPO_ID, 15)
        self.assertEqual(len(resultado), 2)

    @patch("rendimiento.services.requests.get")
    def test_params_status_finished_y_limit(self, mock_get):
        mock_get.return_value = _mock_response_ok({"matches": []})
        get_partidos_equipo("558", 10)
        params = mock_get.call_args[1]["params"]
        self.assertEqual(params["status"], "FINISHED")
        self.assertEqual(params["limit"], 10)
        self.assertIn("/teams/558/matches", mock_get.call_args[0][0])

    @patch("rendimiento.services.requests.get")
    def test_timeout_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            get_partidos_equipo(EQUIPO_ID, 5)
        self.assertIn("tardó", str(ctx.exception).lower())

    @patch("rendimiento.services.requests.get")
    def test_http_404_mensaje_equipo_no_registrado(self, mock_get):
        resp = MagicMock()
        resp.status_code = 404
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            get_partidos_equipo("99999", 5)
        self.assertIn("no está registrado", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_http_400_mensaje_equipo_no_registrado(self, mock_get):
        resp = MagicMock()
        resp.status_code = 400
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            get_partidos_equipo("bad", 5)
        self.assertIn("no está registrado", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_http_429_lanza_runtime(self, mock_get):
        resp = MagicMock()
        resp.status_code = 429
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            get_partidos_equipo(EQUIPO_ID, 5)
        self.assertIn("límite", str(ctx.exception))

    @patch("rendimiento.services.requests.get")
    def test_connection_error_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError()
        with self.assertRaises(RuntimeError):
            get_partidos_equipo(EQUIPO_ID, 5)


# ──────────────────────────────────────────────────────────────────────────────
# 4. procesar_rendimiento (Pandas)
# ──────────────────────────────────────────────────────────────────────────────

class ProcesarRendimientoTests(TestCase):
    def test_lista_vacia_devuelve_dict_vacio(self):
        self.assertEqual(procesar_rendimiento([], EQUIPO_ID), {})

    def test_claves_medias_y_lista_partidos(self):
        r = procesar_rendimiento([PARTIDO_LOCAL, PARTIDO_VISITANTE], EQUIPO_ID)
        self.assertIn("medias", r)
        self.assertIn("lista_partidos", r)

    def test_medias_local_y_visitante(self):
        r = procesar_rendimiento([PARTIDO_LOCAL, PARTIDO_VISITANTE], EQUIPO_ID)
        medias = r["medias"]
        self.assertIn("Local", medias)
        self.assertIn("Visitante", medias)
        self.assertAlmostEqual(medias["Local"]["Goles_Favor"], 3.0)
        self.assertAlmostEqual(medias["Visitante"]["Goles_Favor"], 2.0)

    def test_lista_partidos_por_condicion(self):
        r = procesar_rendimiento([PARTIDO_LOCAL, PARTIDO_VISITANTE], EQUIPO_ID)
        self.assertEqual(len(r["lista_partidos"]["Local"]), 1)
        self.assertEqual(len(r["lista_partidos"]["Visitante"]), 1)

    def test_renombra_columnas_en_lista(self):
        r = procesar_rendimiento([PARTIDO_LOCAL], EQUIPO_ID)
        fila = r["lista_partidos"]["Local"][0]
        self.assertIn("Fecha", fila)
        self.assertIn("Equipo_Local", fila)
        self.assertIn("Resultado_Local", fila)
        self.assertIn("Equipo_Visitante", fila)

    def test_fecha_truncada_a_10_caracteres(self):
        r = procesar_rendimiento([PARTIDO_LOCAL], EQUIPO_ID)
        self.assertEqual(r["lista_partidos"]["Local"][0]["Fecha"], "2024-01-10")

    def test_solo_partidos_locales(self):
        r = procesar_rendimiento([PARTIDO_LOCAL], EQUIPO_ID)
        self.assertIn("Local", r["medias"])
        self.assertNotIn("Visitante", r["lista_partidos"])

    def test_diferencia_goles_en_medias(self):
        r = procesar_rendimiento([PARTIDO_LOCAL], EQUIPO_ID)
        self.assertAlmostEqual(r["medias"]["Local"]["Diferencia_Goles"], 3.0)

    def test_varios_partidos_misma_condicion_promedia(self):
        otro_local = _partido("2024-03-01T18:00:00Z", 558, "Dep", 101, "R2", 1, 1)
        r = procesar_rendimiento([PARTIDO_LOCAL, otro_local], EQUIPO_ID)
        self.assertAlmostEqual(r["medias"]["Local"]["Goles_Favor"], 2.0)


# ──────────────────────────────────────────────────────────────────────────────
# 5. _construir_datos_grafica
# ──────────────────────────────────────────────────────────────────────────────

class ConstruirDatosGraficaTests(TestCase):
    def test_estructura_claves(self):
        datos = _construir_datos_grafica([PARTIDO_LOCAL], EQUIPO_ID)
        for clave in (
            "labels", "condiciones", "rivales",
            "goles_favor", "goles_contra", "diferencia_goles",
        ):
            with self.subTest(clave=clave):
                self.assertIn(clave, datos)

    def test_partido_local_valores(self):
        datos = _construir_datos_grafica([PARTIDO_LOCAL], EQUIPO_ID)
        self.assertEqual(datos["goles_favor"][0], 3)
        self.assertEqual(datos["goles_contra"][0], 0)
        self.assertEqual(datos["condiciones"][0], "L")
        self.assertEqual(datos["diferencia_goles"][0], 3)

    def test_partido_visitante_condicion_v(self):
        datos = _construir_datos_grafica([PARTIDO_VISITANTE], EQUIPO_ID)
        self.assertEqual(datos["condiciones"][0], "V")
        self.assertEqual(datos["goles_favor"][0], 2)
        self.assertEqual(datos["goles_contra"][0], 1)

    def test_omite_partido_sin_marcador(self):
        incompleto = {
            "utcDate": "2024-01-01T12:00:00Z",
            "homeTeam": {"id": 558, "name": "Dep"},
            "awayTeam": {"id": 1, "name": "X"},
            "score": {"fullTime": {"home": None, "away": None}},
        }
        datos = _construir_datos_grafica([incompleto, PARTIDO_LOCAL], EQUIPO_ID)
        self.assertEqual(len(datos["labels"]), 1)

    def test_ordena_cronologico_invertido(self):
        p1 = _partido("2024-01-01T18:00:00Z", 558, "Dep", 1, "A", 1, 0)
        p2 = _partido("2024-03-01T18:00:00Z", 558, "Dep", 2, "B", 2, 0)
        datos = _construir_datos_grafica([p1, p2], EQUIPO_ID)
        self.assertTrue(datos["labels"][0].startswith("2024-03-01"))

    def test_lista_vacia_devuelve_listas_vacias(self):
        datos = _construir_datos_grafica([], EQUIPO_ID)
        self.assertEqual(datos["labels"], [])

    def test_label_contiene_fecha_y_rival(self):
        datos = _construir_datos_grafica([PARTIDO_LOCAL], EQUIPO_ID)
        self.assertIn("2024-01-10", datos["labels"][0])
        self.assertIn("Rival A", datos["labels"][0])


# ──────────────────────────────────────────────────────────────────────────────
# 6. Vista dashboard
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class DashboardViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="renduser", password="testpass")
        self.url = reverse("rendimiento:dashboard")

    def test_sin_login_redirige(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)
        self.assertIn("login", r["Location"])

    def test_get_autenticado_renderiza_dashboard(self):
        self.client.login(username="renduser", password="testpass")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "rendimiento/dashboard.html")


# ──────────────────────────────────────────────────────────────────────────────
# 7. Vista index
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class IndexViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="indexuser", password="testpass")
        self.url = reverse("rendimiento:index")

    def test_sin_login_redirige(self):
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 302)

    def test_get_sin_parametros_vacio(self):
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url)
        self.assertEqual(r.status_code, 200)
        self.assertTemplateUsed(r, "rendimiento/index.html")
        self.assertIsNone(r.context.get("resultados"))

    @patch("rendimiento.views.procesar_rendimiento")
    @patch("rendimiento.views.get_partidos_equipo")
    def test_get_con_team_id_carga_resultados(self, mock_partidos, mock_procesar):
        mock_partidos.return_value = [PARTIDO_LOCAL]
        mock_procesar.return_value = {
            "medias": {"Local": {}},
            "lista_partidos": {"Local": []},
        }
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"team_id": EQUIPO_ID, "equipo": "Deportivo"})
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.context["resultados"])
        self.assertIn("grafica_rendimiento_json", r.context)

    @patch("rendimiento.views.buscar_equipos")
    def test_sin_candidatos_muestra_error(self, mock_buscar):
        mock_buscar.return_value = []
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"equipo": "EquipoInexistente"})
        self.assertIn("error_api", r.context)
        self.assertIn("No se encontró", r.context["error_api"])

    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.buscar_equipos")
    def test_multiples_candidatos_muestra_selector(self, mock_buscar, mock_partidos):
        mock_buscar.return_value = CANDIDATOS_MUESTRA
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"equipo": "Deportivo"})
        self.assertIsNotNone(r.context["candidatos"])
        self.assertIn("Selecciona", r.context["error_api"])

    @patch("rendimiento.views.procesar_rendimiento")
    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.buscar_equipos")
    def test_candidato_exacto_carga_directo(
        self, mock_buscar, mock_partidos, mock_procesar
    ):
        mock_buscar.return_value = CANDIDATOS_MUESTRA
        mock_partidos.return_value = [PARTIDO_LOCAL]
        mock_procesar.return_value = {"medias": {}, "lista_partidos": {}}
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"equipo": "RC Deportivo de La Coruña"})
        self.assertIsNone(r.context.get("candidatos"))
        self.assertEqual(r.context["equipo_id"], "558")

    @patch("rendimiento.views.procesar_rendimiento")
    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.buscar_equipos")
    def test_un_solo_candidato_carga_directo(
        self, mock_buscar, mock_partidos, mock_procesar
    ):
        mock_buscar.return_value = [CANDIDATOS_MUESTRA[0]]
        mock_partidos.return_value = [PARTIDO_LOCAL]
        mock_procesar.return_value = {"medias": {}, "lista_partidos": {}}
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"equipo": "Algo que matchea uno"})
        self.assertIsNone(r.context.get("candidatos"))
        mock_partidos.assert_called_once()

    @patch("rendimiento.views.get_partidos_equipo")
    def test_runtime_error_en_contexto(self, mock_partidos):
        mock_partidos.side_effect = RuntimeError("límite de peticiones")
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"team_id": EQUIPO_ID, "equipo": "Dep"})
        self.assertIn("error_api", r.context)
        self.assertIn("límite", r.context["error_api"])

    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.procesar_rendimiento", return_value={})
    def test_partidos_vacios_sin_medias(self, mock_procesar, mock_partidos):
        mock_partidos.return_value = []
        self.client.login(username="indexuser", password="testpass")
        r = self.client.get(self.url, {"team_id": EQUIPO_ID})
        self.assertNotIn("medias", r.context)

    def test_n_partidos_invalido_usa_15(self):
        self.client.login(username="indexuser", password="testpass")
        with patch("rendimiento.views.get_partidos_equipo") as mock_p:
            mock_p.return_value = []
            with patch("rendimiento.views.procesar_rendimiento", return_value={}):
                self.client.get(self.url, {"team_id": EQUIPO_ID, "n_partidos": "abc"})
        mock_p.assert_called_once_with(EQUIPO_ID, 15)

    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.procesar_rendimiento", return_value={})
    def test_n_partidos_limitado_a_30(self, mock_procesar, mock_partidos):
        mock_partidos.return_value = []
        self.client.login(username="indexuser", password="testpass")
        self.client.get(self.url, {"team_id": EQUIPO_ID, "n_partidos": "100"})
        mock_partidos.assert_called_once_with(EQUIPO_ID, 30)

    @patch("rendimiento.views.get_partidos_equipo")
    @patch("rendimiento.views.procesar_rendimiento", return_value={})
    def test_n_partidos_minimo_1(self, mock_procesar, mock_partidos):
        mock_partidos.return_value = []
        self.client.login(username="indexuser", password="testpass")
        self.client.get(self.url, {"team_id": EQUIPO_ID, "n_partidos": "0"})
        mock_partidos.assert_called_once_with(EQUIPO_ID, 1)


# ──────────────────────────────────────────────────────────────────────────────
# 8. Autocomplete equipos (sin login_required)
# ──────────────────────────────────────────────────────────────────────────────

class AutocompleteEquiposTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.url = reverse("rendimiento:autocomplete")

    def test_sin_login_permite_acceso(self):
        r = self.client.get(self.url, {"q": "dep"})
        self.assertEqual(r.status_code, 200)

    def test_query_corta_vacia(self):
        r = self.client.get(self.url, {"q": "d"})
        self.assertEqual(r.json()["sugerencias"], [])

    @patch("rendimiento.views.buscar_equipos")
    def test_devuelve_sugerencias_con_claves(self, mock_buscar):
        mock_buscar.return_value = CANDIDATOS_MUESTRA
        data = self.client.get(self.url, {"q": "Dep"}).json()
        self.assertEqual(len(data["sugerencias"]), 3)
        primera = data["sugerencias"][0]
        for clave in ("label", "id", "pais", "logo"):
            with self.subTest(clave=clave):
                self.assertIn(clave, primera)

    @patch("rendimiento.views.buscar_equipos")
    def test_maximo_8_sugerencias(self, mock_buscar):
        mock_buscar.return_value = [
            {"id": str(i), "nombre": f"Club {i}", "pais": "", "logo": ""}
            for i in range(20)
        ]
        data = self.client.get(self.url, {"q": "Club"}).json()
        self.assertLessEqual(len(data["sugerencias"]), 8)

    @patch("rendimiento.views.buscar_equipos")
    def test_runtime_error_devuelve_lista_vacia(self, mock_buscar):
        mock_buscar.side_effect = RuntimeError("límite")
        data = self.client.get(self.url, {"q": "Dep"}).json()
        self.assertEqual(data["sugerencias"], [])
