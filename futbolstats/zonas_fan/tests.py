"""
zonas_fan/tests.py
==================
F4 — Zonas fan y restauración.

Estructura
----------
  ParsearCoordsTests              — utilidad pura _parsear_coords
  TraducirAmenityTests            — _traducir_amenity
  DireccionDesdeTagsTests         — _direccion_desde_tags
  DistanciaMetrosTests            — _distancia_metros (haversine)
  EsErrorTransitorioOverpassTests — detección de errores retry
  GeocodificarNominatimTests      — GET Nominatim mockeado
  ObtenerCoordenadasEstadioTests  — API-Football + Nominatim mockeados
  BuscarLocalesCercanosTests      — Overpass + Pandas mockeados
  EjecutarQueryOverpassTests      — mirrors, retry y backoff
  BuscarEquiposAutocompleteTests  — GET /teams para autocomplete
  ZonasViewTests                  — vista principal (login, GET, POST)
  AutocompleteZonasViewTests      — endpoint JSON autocomplete
"""

from unittest.mock import patch, MagicMock, call

import requests as _requests_module

from django.contrib.auth.models import User
from django.contrib.messages import get_messages
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from zonas_fan.services import (
    MAX_LOCALES,
    OVERPASS_BACKOFF_SECONDS,
    OVERPASS_MIRRORS,
    _direccion_desde_tags,
    _distancia_metros,
    _ejecutar_query_overpass,
    _es_error_transitorio_overpass,
    _geocodificar_nominatim,
    _parsear_coords,
    _traducir_amenity,
    buscar_equipos_autocomplete,
    buscar_locales_cercanos,
    obtener_coordenadas_estadio,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers compartidos
# ──────────────────────────────────────────────────────────────────────────────

LAT_ESTADIO = 43.3623
LNG_ESTADIO = -8.4115


def _mock_response_ok(json_payload, status_code=200):
    m = MagicMock()
    m.status_code = status_code
    m.raise_for_status = MagicMock()
    m.json.return_value = json_payload
    return m


def _payload_equipo_api_football(
    nombre="RC Deportivo de La Coruña",
    estadio="Estadio Abanca-Riazor",
    ciudad="La Coruña",
    pais="Spain",
):
    return {
        "errors": {},
        "response": [
            {
                "team": {"name": nombre, "country": pais},
                "venue": {"name": estadio, "city": ciudad},
            }
        ],
    }


def _make_overpass_node(lat, lon, tags):
    node = MagicMock()
    node.lat = lat
    node.lon = lon
    node.tags = tags
    return node


def _make_overpass_way(center_lat, center_lon, tags):
    way = MagicMock()
    way.center_lat = center_lat
    way.center_lon = center_lon
    way.tags = tags
    return way


def _make_overpass_relation(center_lat, center_lon, tags):
    rel = MagicMock()
    rel.center_lat = center_lat
    rel.center_lon = center_lon
    rel.tags = tags
    return rel


def _overpass_result(nodes=None, ways=None, relations=None):
    result = MagicMock()
    result.nodes = nodes or []
    result.ways = ways or []
    result.relations = relations or []
    return result


# ──────────────────────────────────────────────────────────────────────────────
# 1. _parsear_coords
# ──────────────────────────────────────────────────────────────────────────────

class ParsearCoordsTests(TestCase):
    def test_floats_validos(self):
        self.assertEqual(_parsear_coords(43.36, -8.41), (43.36, -8.41))

    def test_strings_numericos(self):
        self.assertEqual(_parsear_coords("43.36", "-8.41"), (43.36, -8.41))

    def test_lat_none(self):
        self.assertIsNone(_parsear_coords(None, -8.41))

    def test_lng_none(self):
        self.assertIsNone(_parsear_coords(43.36, None))

    def test_string_no_numerico(self):
        self.assertIsNone(_parsear_coords("abc", "-8.41"))

    def test_ambos_none(self):
        self.assertIsNone(_parsear_coords(None, None))


# ──────────────────────────────────────────────────────────────────────────────
# 2. _traducir_amenity
# ──────────────────────────────────────────────────────────────────────────────

class TraducirAmenityTests(TestCase):
    def test_bar(self):
        self.assertEqual(_traducir_amenity("bar"), "Bar")

    def test_pub(self):
        self.assertEqual(_traducir_amenity("pub"), "Pub")

    def test_restaurant(self):
        self.assertEqual(_traducir_amenity("restaurant"), "Restaurante")

    def test_cafe(self):
        self.assertEqual(_traducir_amenity("cafe"), "Cafeteria")

    def test_mayusculas(self):
        self.assertEqual(_traducir_amenity("BAR"), "Bar")

    def test_desconocido(self):
        self.assertEqual(_traducir_amenity("biergarten"), "Local")

    def test_none(self):
        self.assertEqual(_traducir_amenity(None), "Local")

    def test_vacio(self):
        self.assertEqual(_traducir_amenity(""), "Local")


# ──────────────────────────────────────────────────────────────────────────────
# 3. _direccion_desde_tags
# ──────────────────────────────────────────────────────────────────────────────

class DireccionDesdeTagsTests(TestCase):
    def test_direccion_completa(self):
        tags = {
            "addr:street": "Calle Mayor",
            "addr:housenumber": "12",
            "addr:city": "La Coruña",
        }
        self.assertEqual(_direccion_desde_tags(tags), "Calle Mayor 12, La Coruña")

    def test_solo_calle(self):
        tags = {"addr:street": "Rúa Real", "addr:housenumber": ""}
        self.assertEqual(_direccion_desde_tags(tags), "Rúa Real")

    def test_sin_datos_devuelve_na(self):
        self.assertEqual(_direccion_desde_tags({}), "N/A")

    def test_solo_ciudad(self):
        self.assertEqual(_direccion_desde_tags({"addr:city": "Vigo"}), "Vigo")


# ──────────────────────────────────────────────────────────────────────────────
# 4. _distancia_metros
# ──────────────────────────────────────────────────────────────────────────────

class DistanciaMetrosTests(TestCase):
    def test_mismo_punto_cero_metros(self):
        self.assertEqual(_distancia_metros(LAT_ESTADIO, LNG_ESTADIO, LAT_ESTADIO, LNG_ESTADIO), 0)

    def test_distancia_positiva_cercana(self):
        d = _distancia_metros(LAT_ESTADIO, LNG_ESTADIO, LAT_ESTADIO + 0.001, LNG_ESTADIO)
        self.assertGreater(d, 0)
        self.assertLess(d, 200)

    def test_devuelve_entero(self):
        d = _distancia_metros(0.0, 0.0, 0.0, 1.0)
        self.assertIsInstance(d, int)


# ──────────────────────────────────────────────────────────────────────────────
# 5. _es_error_transitorio_overpass
# ──────────────────────────────────────────────────────────────────────────────

class EsErrorTransitorioOverpassTests(TestCase):
    def test_timeout(self):
        self.assertTrue(_es_error_transitorio_overpass("Gateway timeout"))

    def test_429(self):
        self.assertTrue(_es_error_transitorio_overpass("HTTP 429 Too Many Requests"))

    def test_502(self):
        self.assertTrue(_es_error_transitorio_overpass("502 Bad Gateway"))

    def test_rate_limit(self):
        self.assertTrue(_es_error_transitorio_overpass("rate limit exceeded"))

    def test_error_permanente(self):
        self.assertFalse(_es_error_transitorio_overpass("syntax error in query"))

    def test_none_y_vacio(self):
        self.assertFalse(_es_error_transitorio_overpass(None))
        self.assertFalse(_es_error_transitorio_overpass(""))


# ──────────────────────────────────────────────────────────────────────────────
# 6. _geocodificar_nominatim
# ──────────────────────────────────────────────────────────────────────────────

class GeocodificarNominatimTests(TestCase):
    @patch("zonas_fan.services.requests.get")
    def test_exito_devuelve_tupla(self, mock_get):
        mock_get.return_value = _mock_response_ok(
            [{"lat": "43.3623", "lon": "-8.4115"}]
        )
        coords = _geocodificar_nominatim("Estadio Riazor, La Coruña")
        self.assertEqual(coords, (43.3623, -8.4115))
        mock_get.assert_called_once()
        params = mock_get.call_args[1]["params"]
        self.assertEqual(params["q"], "Estadio Riazor, La Coruña")
        self.assertEqual(params["limit"], 1)

    @patch("zonas_fan.services.requests.get")
    def test_lista_vacia_devuelve_none(self, mock_get):
        mock_get.return_value = _mock_response_ok([])
        self.assertIsNone(_geocodificar_nominatim("Lugar inexistente XYZ"))

    @patch("zonas_fan.services.requests.get")
    def test_excepcion_red_devuelve_none(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        self.assertIsNone(_geocodificar_nominatim("query"))

    @patch("zonas_fan.services.requests.get")
    def test_http_error_devuelve_none(self, mock_get):
        m = MagicMock()
        m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError()
        mock_get.return_value = m
        self.assertIsNone(_geocodificar_nominatim("query"))


# ──────────────────────────────────────────────────────────────────────────────
# 7. obtener_coordenadas_estadio
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(API_FOOTBALL_KEY="test-key")
class ObtenerCoordenadasEstadioTests(TestCase):
    @override_settings(API_FOOTBALL_KEY="")
    def test_sin_api_key_lanza_runtime(self):
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Deportivo")
        self.assertIn("API_FOOTBALL_KEY", str(ctx.exception))

    @patch("zonas_fan.services._geocodificar_nominatim")
    @patch("zonas_fan.services.requests.get")
    def test_flujo_completo_exitoso(self, mock_get, mock_geo):
        mock_get.return_value = _mock_response_ok(_payload_equipo_api_football())
        mock_geo.return_value = (LAT_ESTADIO, LNG_ESTADIO)

        resultado = obtener_coordenadas_estadio("RC Deportivo de La Coruña")

        self.assertEqual(resultado["estadio"], "Estadio Abanca-Riazor")
        self.assertEqual(resultado["lat"], LAT_ESTADIO)
        self.assertEqual(resultado["lng"], LNG_ESTADIO)
        mock_geo.assert_called_once()

    @patch("zonas_fan.services._geocodificar_nominatim")
    @patch("zonas_fan.services.requests.get")
    def test_preferencia_coincidencia_exacta_de_nombre(self, mock_get, mock_geo):
        payload = {
            "errors": {},
            "response": [
                {
                    "team": {"name": "Otro Equipo", "country": "Spain"},
                    "venue": {"name": "Estadio A", "city": "Madrid"},
                },
                {
                    "team": {"name": "RC Deportivo de La Coruña", "country": "Spain"},
                    "venue": {"name": "Riazor", "city": "La Coruña"},
                },
            ],
        }
        mock_get.return_value = _mock_response_ok(payload)
        mock_geo.return_value = (LAT_ESTADIO, LNG_ESTADIO)

        obtener_coordenadas_estadio("RC Deportivo de La Coruña")

        # Primera llamada a Nominatim debe usar el estadio del equipo exacto
        primera_query = mock_geo.call_args_list[0][0][0]
        self.assertIn("Riazor", primera_query)

    @patch("zonas_fan.services._geocodificar_nominatim")
    @patch("zonas_fan.services.requests.get")
    def test_cadena_geocodificacion_tres_intentos(self, mock_get, mock_geo):
        mock_get.return_value = _mock_response_ok(_payload_equipo_api_football())
        mock_geo.side_effect = [None, None, (LAT_ESTADIO, LNG_ESTADIO)]

        resultado = obtener_coordenadas_estadio("RC Deportivo de La Coruña")

        self.assertEqual(mock_geo.call_count, 3)
        self.assertEqual(resultado["lat"], LAT_ESTADIO)

    @patch("zonas_fan.services._geocodificar_nominatim", return_value=None)
    @patch("zonas_fan.services.requests.get")
    def test_nominatim_falla_lanza_runtime(self, mock_get, mock_geo):
        mock_get.return_value = _mock_response_ok(_payload_equipo_api_football())
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Equipo Perdido")
        self.assertIn("No se encuentra el estadio", str(ctx.exception))

    @patch("zonas_fan.services.requests.get")
    def test_respuesta_vacia_lanza_runtime(self, mock_get):
        mock_get.return_value = _mock_response_ok({"errors": {}, "response": []})
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Inexistente")
        self.assertIn("No se encuentra el estadio", str(ctx.exception))

    @patch("zonas_fan.services.requests.get")
    def test_response_no_lista_lanza_runtime(self, mock_get):
        mock_get.return_value = _mock_response_ok({"errors": {}, "response": {}})
        with self.assertRaises(RuntimeError):
            obtener_coordenadas_estadio("X")

    @patch("zonas_fan.services.requests.get")
    def test_cuenta_suspendida(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "errors": {"account": "Account suspended"},
            "response": [],
        })
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Deportivo")
        self.assertIn("suspendida", str(ctx.exception))

    @patch("zonas_fan.services.requests.get")
    def test_limite_diario_peticiones(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "errors": {"requests": "Reached the request limit per day."},
            "response": [],
        })
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Deportivo")
        self.assertIn("límite diario", str(ctx.exception))

    @patch("zonas_fan.services.requests.get")
    def test_error_generico_api_football(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "errors": {"token": "Invalid API key"},
            "response": [],
        })
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Deportivo")
        self.assertIn("API-Football", str(ctx.exception))

    @patch("zonas_fan.services.requests.get")
    def test_request_exception_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError("refused")
        with self.assertRaises(RuntimeError) as ctx:
            obtener_coordenadas_estadio("Deportivo")
        self.assertIn("API-Football", str(ctx.exception))

    @patch("zonas_fan.services._geocodificar_nominatim")
    @patch("zonas_fan.services.requests.get")
    def test_venue_sin_nombre_usa_nombre_equipo(self, mock_get, mock_geo):
        payload = {
            "errors": {},
            "response": [
                {
                    "team": {"name": "Equipo Test", "country": "Spain"},
                    "venue": {"name": None, "city": "Ciudad"},
                }
            ],
        }
        mock_get.return_value = _mock_response_ok(payload)
        mock_geo.return_value = (40.0, -3.0)

        resultado = obtener_coordenadas_estadio("Equipo Test")

        self.assertEqual(resultado["estadio"], "Equipo Test")


# ──────────────────────────────────────────────────────────────────────────────
# 8. buscar_locales_cercanos
# ──────────────────────────────────────────────────────────────────────────────

class BuscarLocalesCercanosTests(TestCase):
    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_sin_resultados_devuelve_lista_vacia(self, mock_overpass):
        mock_overpass.return_value = _overpass_result()
        self.assertEqual(buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO), [])

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_nodo_bar_con_nombre(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            nodes=[_make_overpass_node(
                LAT_ESTADIO + 0.0001,
                LNG_ESTADIO,
                {"amenity": "bar", "name": "Bar Riazor"},
            )]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO, radio_m=1000)
        self.assertEqual(len(locales), 1)
        self.assertEqual(locales[0]["nombre"], "Bar Riazor")
        self.assertEqual(locales[0]["categoria"], "Bar")
        self.assertIn("distancia", locales[0])
        self.assertIsInstance(locales[0]["distancia"], int)

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_sin_nombre_usa_categoria_sin_nombre(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            nodes=[_make_overpass_node(
                LAT_ESTADIO + 0.0001,
                LNG_ESTADIO,
                {"amenity": "restaurant"},
            )]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertEqual(locales[0]["nombre"], "Restaurante sin nombre")

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_way_con_centro(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            ways=[_make_overpass_way(
                LAT_ESTADIO + 0.0002,
                LNG_ESTADIO + 0.0001,
                {"amenity": "cafe", "name": "Café Estadio"},
            )]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertEqual(len(locales), 1)
        self.assertEqual(locales[0]["categoria"], "Cafeteria")

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_relation_con_centro(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            relations=[_make_overpass_relation(
                LAT_ESTADIO + 0.0001,
                LNG_ESTADIO,
                {"amenity": "pub", "name": "Pub Afición"},
            )]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertEqual(locales[0]["categoria"], "Pub")

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_nodo_sin_coordenadas_se_ignora(self, mock_overpass):
        node = MagicMock()
        node.lat = None
        node.lon = None
        node.tags = {"amenity": "bar", "name": "Invisible"}
        mock_overpass.return_value = _overpass_result(nodes=[node])
        self.assertEqual(buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO), [])

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_way_sin_centro_se_ignora(self, mock_overpass):
        way = MagicMock()
        way.center_lat = None
        way.center_lon = None
        way.tags = {"amenity": "bar", "name": "Way sin centro"}
        mock_overpass.return_value = _overpass_result(ways=[way])
        self.assertEqual(buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO), [])

    @patch("zonas_fan.services._distancia_metros")
    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_filtra_por_radio(self, mock_overpass, mock_dist):
        mock_overpass.return_value = _overpass_result(
            nodes=[_make_overpass_node(
                LAT_ESTADIO,
                LNG_ESTADIO,
                {"amenity": "bar", "name": "Lejos"},
            )]
        )
        mock_dist.return_value = 2000  
        self.assertEqual(buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO, radio_m=500), [])

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_ordenados_por_distancia_ascendente(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            nodes=[
                _make_overpass_node(
                    LAT_ESTADIO + 0.001,
                    LNG_ESTADIO,
                    {"amenity": "bar", "name": "Lejos"},
                ),
                _make_overpass_node(
                    LAT_ESTADIO + 0.00005,
                    LNG_ESTADIO,
                    {"amenity": "bar", "name": "Cerca"},
                ),
            ]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertEqual(locales[0]["nombre"], "Cerca")
        self.assertLessEqual(locales[0]["distancia"], locales[1]["distancia"])

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_limite_max_locales(self, mock_overpass):
        nodos = [
            _make_overpass_node(
                LAT_ESTADIO + i * 0.00001,
                LNG_ESTADIO,
                {"amenity": "bar", "name": f"Bar {i}"},
            )
            for i in range(MAX_LOCALES + 10)
        ]
        mock_overpass.return_value = _overpass_result(nodes=nodos)
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertEqual(len(locales), MAX_LOCALES)

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_direccion_desde_tags_osm(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            nodes=[_make_overpass_node(
                LAT_ESTADIO + 0.0001,
                LNG_ESTADIO,
                {
                    "amenity": "restaurant",
                    "name": "Tapería",
                    "addr:street": "Av. Finisterre",
                    "addr:housenumber": "5",
                    "addr:city": "A Coruña",
                },
            )]
        )
        locales = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertIn("Av. Finisterre", locales[0]["direccion"])

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_tipos_python_nativos_en_salida(self, mock_overpass):
        mock_overpass.return_value = _overpass_result(
            nodes=[_make_overpass_node(
                LAT_ESTADIO + 0.0001,
                LNG_ESTADIO,
                {"amenity": "bar", "name": "Test"},
            )]
        )
        loc = buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)[0]
        self.assertIsInstance(loc["distancia"], int)
        self.assertIsInstance(loc["lat"], float)
        self.assertIsInstance(loc["lng"], float)

    @patch("zonas_fan.services._ejecutar_query_overpass")
    def test_overpass_falla_lanza_runtime(self, mock_overpass):
        mock_overpass.side_effect = Exception("overpass down")
        with self.assertRaises(RuntimeError) as ctx:
            buscar_locales_cercanos(LAT_ESTADIO, LNG_ESTADIO)
        self.assertIn("OpenStreetMap/Overpass", str(ctx.exception))


# ──────────────────────────────────────────────────────────────────────────────
# 9. _ejecutar_query_overpass
# ──────────────────────────────────────────────────────────────────────────────

class EjecutarQueryOverpassTests(TestCase):
    @patch("zonas_fan.services.overpy.Overpass")
    def test_exito_en_primer_mirror(self, mock_overpass_cls):
        api = MagicMock()
        api.query.return_value = _overpass_result()
        mock_overpass_cls.return_value = api

        resultado = _ejecutar_query_overpass("[out:json]; node; out;")

        self.assertIsNotNone(resultado)
        mock_overpass_cls.assert_called_once_with(url=OVERPASS_MIRRORS[0])

    @patch("zonas_fan.services.time.sleep")
    @patch("zonas_fan.services.overpy.Overpass")
    def test_retry_en_error_transitorio(self, mock_overpass_cls, mock_sleep):
        api = MagicMock()
        api.query.side_effect = [
            Exception("504 Gateway Timeout"),
            _overpass_result(),
        ]
        mock_overpass_cls.return_value = api

        _ejecutar_query_overpass("query")

        self.assertEqual(api.query.call_count, 2)
        mock_sleep.assert_called_once_with(OVERPASS_BACKOFF_SECONDS[0])

    @patch("zonas_fan.services.time.sleep")
    @patch("zonas_fan.services.overpy.Overpass")
    def test_segundo_mirror_si_primero_falla_permanentemente(self, mock_overpass_cls, mock_sleep):
        api1 = MagicMock()
        api1.query.side_effect = Exception("syntax error permanent")

        api2 = MagicMock()
        api2.query.return_value = _overpass_result()

        mock_overpass_cls.side_effect = [api1, api2]

        _ejecutar_query_overpass("query")

        self.assertEqual(mock_overpass_cls.call_count, 2)
        urls = [c[1]["url"] for c in mock_overpass_cls.call_args_list]
        self.assertEqual(urls[0], OVERPASS_MIRRORS[0])
        self.assertEqual(urls[1], OVERPASS_MIRRORS[1])

    @patch("zonas_fan.services.time.sleep")
    @patch("zonas_fan.services.overpy.Overpass")
    def test_todos_los_mirrors_fallan_lanza_runtime(self, mock_overpass_cls, mock_sleep):
        api = MagicMock()
        api.query.side_effect = Exception("hard failure")
        mock_overpass_cls.return_value = api

        with self.assertRaises(RuntimeError) as ctx:
            _ejecutar_query_overpass("query")
        self.assertIn("temporalmente saturado", str(ctx.exception))
        self.assertEqual(mock_overpass_cls.call_count, len(OVERPASS_MIRRORS))


# ──────────────────────────────────────────────────────────────────────────────
# 10. buscar_equipos_autocomplete
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(API_FOOTBALL_KEY="test-key")
class BuscarEquiposAutocompleteTests(TestCase):
    def test_query_vacia(self):
        self.assertEqual(buscar_equipos_autocomplete(""), [])

    @override_settings(API_FOOTBALL_KEY="")
    def test_sin_api_key(self):
        self.assertEqual(buscar_equipos_autocomplete("Dep"), [])

    @patch("zonas_fan.services.requests.get")
    def test_devuelve_nombres_hasta_10(self, mock_get):
        equipos = [
            {"team": {"name": f"Equipo {i}"}} for i in range(15)
        ]
        mock_get.return_value = _mock_response_ok({"response": equipos})
        resultado = buscar_equipos_autocomplete("Equ")
        self.assertEqual(len(resultado), 10)
        self.assertEqual(resultado[0], "Equipo 0")

    @patch("zonas_fan.services.requests.get")
    def test_ignora_entradas_sin_nombre(self, mock_get):
        mock_get.return_value = _mock_response_ok({
            "response": [
                {"team": {}},
                {"team": {"name": "RC Deportivo"}},
            ]
        })
        self.assertEqual(buscar_equipos_autocomplete("Dep"), ["RC Deportivo"])

    @patch("zonas_fan.services.requests.get")
    def test_excepcion_devuelve_lista_vacia(self, mock_get):
        mock_get.side_effect = Exception("network")
        self.assertEqual(buscar_equipos_autocomplete("Dep"), [])

    @patch("zonas_fan.services.requests.get")
    def test_timeout_devuelve_lista_vacia(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        self.assertEqual(buscar_equipos_autocomplete("Dep"), [])


# ──────────────────────────────────────────────────────────────────────────────
# 11. Vista zonas
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class ZonasViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="zonasuser", password="testpass")
        self.url = reverse("zonas_fan:zonas")

    def test_get_sin_login_redirige(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_sin_login_redirige(self):
        response = self.client.post(self.url, {"equipo": "Deportivo"})
        self.assertEqual(response.status_code, 302)

    def test_get_autenticado_renderiza_template(self):
        self.client.login(username="zonasuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "zonas_fan/zonas.html")
        self.assertIsNone(response.context["locales"])
        self.assertIn("equipos_sugeridos", response.context)

    def test_post_sin_nombre_muestra_error(self):
        self.client.login(username="zonasuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "", "radio": "1000"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Introduce" in m for m in msgs))

    @patch("zonas_fan.views.buscar_locales_cercanos")
    @patch("zonas_fan.views.obtener_coordenadas_estadio")
    def test_post_exitoso_con_locales(self, mock_coords, mock_locales):
        mock_coords.return_value = {
            "estadio": "Riazor",
            "lat": LAT_ESTADIO,
            "lng": LNG_ESTADIO,
        }
        mock_locales.return_value = [
            {
                "nombre": "Bar Test",
                "categoria": "Bar",
                "distancia": 120,
                "direccion": "N/A",
                "lat": LAT_ESTADIO + 0.0001,
                "lng": LNG_ESTADIO,
            }
        ]
        self.client.login(username="zonasuser", password="testpass")
        response = self.client.post(
            self.url,
            {"equipo": "RC Deportivo de La Coruña", "radio": "800"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["locales"]), 1)
        self.assertEqual(response.context["estadio"], "Riazor")
        self.assertEqual(response.context["radio"], 800)
        self.assertIn("locales_json", response.context)
        self.assertIn("mapa_coords_json", response.context)
        mock_locales.assert_called_once_with(LAT_ESTADIO, LNG_ESTADIO, 800)

    @patch("zonas_fan.views.buscar_locales_cercanos", return_value=[])
    @patch("zonas_fan.views.obtener_coordenadas_estadio")
    def test_post_sin_locales_muestra_info(self, mock_coords, mock_locales):
        mock_coords.return_value = {
            "estadio": "Riazor",
            "lat": LAT_ESTADIO,
            "lng": LNG_ESTADIO,
        }
        self.client.login(username="zonasuser", password="testpass")
        response = self.client.post(
            self.url,
            {"equipo": "Deportivo", "radio": "1000"},
        )
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("No se encontraron locales" in m for m in msgs))

    @patch("zonas_fan.views.obtener_coordenadas_estadio")
    def test_post_runtime_error_muestra_error(self, mock_coords):
        mock_coords.side_effect = RuntimeError("límite diario alcanzado")
        self.client.login(username="zonasuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "Deportivo", "radio": "1000"})
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("límite" in m for m in msgs))

    @patch("zonas_fan.views.buscar_locales_cercanos")
    @patch("zonas_fan.views.obtener_coordenadas_estadio")
    def test_post_radio_por_defecto_1000(self, mock_coords, mock_locales):
        mock_coords.return_value = {"estadio": "X", "lat": 1.0, "lng": 2.0}
        mock_locales.return_value = []
        self.client.login(username="zonasuser", password="testpass")
        self.client.post(self.url, {"equipo": "Deportivo"})
        mock_locales.assert_called_once_with(1.0, 2.0, 1000)


# ──────────────────────────────────────────────────────────────────────────────
# 12. Vista autocomplete_equipos
# ──────────────────────────────────────────────────────────────────────────────

class AutocompleteZonasViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username="autozonas", password="testpass")
        self.url = reverse("zonas_fan:autocomplete")

    def test_sin_login_redirige(self):
        response = self.client.get(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 302)

    def test_query_un_caracter_devuelve_vacio(self):
        self.client.login(username="autozonas", password="testpass")
        response = self.client.get(self.url, {"q": "D"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sugerencias"], [])

    def test_query_vacia_devuelve_vacio(self):
        self.client.login(username="autozonas", password="testpass")
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.json()["sugerencias"], [])

    @patch("zonas_fan.views.buscar_equipos_autocomplete")
    def test_query_valida_devuelve_sugerencias(self, mock_buscar):
        mock_buscar.return_value = ["RC Deportivo de La Coruña", "Deportivo Alavés"]
        self.client.login(username="autozonas", password="testpass")
        response = self.client.get(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["sugerencias"]), 2)
        mock_buscar.assert_called_once_with("Dep")

    def test_post_devuelve_405(self):
        self.client.login(username="autozonas", password="testpass")
        response = self.client.post(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 405)
