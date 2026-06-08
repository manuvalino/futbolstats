"""
plantilla/tests.py
==================
Valor de mercado de la plantilla

Estructura
----------
  NormalizacionTests           — funciones de utilidad puras, sin red
  ParsearFeeTests              — conversión de strings de fee a euros
  AnalizarValorPlantillaTests  — lógica Pandas: el "modelo" del caso de uso  ← OBLIGATORIO (rúbrica)
  BuscarEquiposTests           — GET /teams mockeado con @patch
  ObtenerPlantillaTests        — GET /players mockeado (paginación + fallback de temporada)
  ObtenerFeesTests             — GET /transfers mockeado (fallo silencioso)
  ValorMercadoViewTests        — vistas HTTP: login, GET, POST (múltiples rutas)
  AutocompleteViewTests        — endpoint JSON de autocompletado

"""

from unittest.mock import patch, MagicMock

import requests as _requests_module 

from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User

from plantilla.services import (
    normalizar_nombre_equipo,
    elegir_candidato_por_nombre,
    analizar_valor_plantilla,
    _parsear_fee,
    buscar_equipos,
    obtener_plantilla,
    obtener_fees_transferencias,
    VALOR_FALLBACK,
    POSICION_ES,
    CURRENT_SEASON,
)


# ──────────────────────────────────────────────────────────────────────────────
# Datos de muestra compartidos
# ──────────────────────────────────────────────────────────────────────────────

JUGADORES_MUESTRA = [
    {"id": "1", "nombre": "Fabri",        "edad": 30, "foto": "", "numero": 1,  "posicion": "Goalkeeper"},
    {"id": "2", "nombre": "Ximo Navarro", "edad": 29, "foto": "", "numero": 2,  "posicion": "Defender"},
    {"id": "3", "nombre": "Lucas Pérez",  "edad": 33, "foto": "", "numero": 7,  "posicion": "Attacker"},
    {"id": "4", "nombre": "Salva Ruiz",   "edad": 28, "foto": "", "numero": 6,  "posicion": "Midfielder"},
    {"id": "5", "nombre": "Trilli",       "edad": 25, "foto": "", "numero": 11, "posicion": "Attacker"},
]

# Fees reales sólo para los jugadores 3 y 4
FEES_MUESTRA = {
    "3": 3_000_000.0,
    "4": 1_500_000.0,
}

CANDIDATOS_MUESTRA = [
    {"id": "558", "nombre": "RC Deportivo de La Coruña", "pais": "Spain", "logo": "https://x.com/dep.png"},
    {"id": "735", "nombre": "Deportivo Alavés",           "pais": "Spain", "logo": "https://x.com/ala.png"},
]


# ──────────────────────────────────────────────────────────────────────────────
# 1. Tests de normalización  (sin red, sin BD)
# ──────────────────────────────────────────────────────────────────────────────

class NormalizacionTests(TestCase):
    """
    Valida normalizar_nombre_equipo y elegir_candidato_por_nombre.
    Son funciones puras: no requieren mocking.
    """

    # normalizar_nombre_equipo ─────────────────────────────────────────────

    def test_normalizar_pasa_a_minusculas(self):
        self.assertEqual(normalizar_nombre_equipo("RC Deportivo"), "rc deportivo")

    def test_normalizar_elimina_acentos(self):
        self.assertEqual(normalizar_nombre_equipo("Atlético"), "atletico")

    def test_normalizar_colapsa_espacios_extra(self):
        self.assertEqual(normalizar_nombre_equipo("  Real   Madrid  "), "real madrid")

    def test_normalizar_cadena_vacia(self):
        self.assertEqual(normalizar_nombre_equipo(""), "")

    def test_normalizar_none(self):
        self.assertEqual(normalizar_nombre_equipo(None), "")

    def test_normalizar_caracteres_especiales(self):
        self.assertEqual(normalizar_nombre_equipo("Borussia Dortmund"), "borussia dortmund")

    # elegir_candidato_por_nombre ─────────────────────────────────────────

    def test_coincidencia_exacta_devuelve_candidato(self):
        resultado = elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, "RC Deportivo de La Coruña")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["id"], "558")

    def test_coincidencia_ignora_acentos_y_mayusculas(self):
        candidatos = [{"id": "77", "nombre": "Atlético de Madrid", "pais": "Spain", "logo": ""}]
        resultado = elegir_candidato_por_nombre(candidatos, "atletico de madrid")
        self.assertIsNotNone(resultado)
        self.assertEqual(resultado["id"], "77")

    def test_sin_coincidencia_devuelve_none(self):
        self.assertIsNone(elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, "Manchester City"))

    def test_lista_vacia_devuelve_none(self):
        self.assertIsNone(elegir_candidato_por_nombre([], "RC Deportivo"))

    def test_nombre_buscado_vacio_devuelve_none(self):
        self.assertIsNone(elegir_candidato_por_nombre(CANDIDATOS_MUESTRA, ""))

    def test_devuelve_primer_exacto_si_hay_varios(self):
        """Si hay dos nombres exactamente iguales, devuelve el primero."""
        duplicados = [
            {"id": "1", "nombre": "FC Test", "pais": "Spain", "logo": ""},
            {"id": "2", "nombre": "FC Test", "pais": "France", "logo": ""},
        ]
        resultado = elegir_candidato_por_nombre(duplicados, "FC Test")
        self.assertEqual(resultado["id"], "1")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tests de parseo de fees  (sin red, sin BD)
# ──────────────────────────────────────────────────────────────────────────────

class ParsearFeeTests(TestCase):
    """Valida _parsear_fee — convierte strings de la API a float en euros."""

    def test_euros_millones(self):
        self.assertAlmostEqual(_parsear_fee("€45M"), 45_000_000, places=0)

    def test_euros_miles(self):
        self.assertAlmostEqual(_parsear_fee("€500K"), 500_000, places=0)

    def test_euros_decimal(self):
        self.assertAlmostEqual(_parsear_fee("€12.5M"), 12_500_000, places=0)

    def test_libras_aplica_factor_cambio(self):
        resultado = _parsear_fee("£10M")
        self.assertAlmostEqual(resultado, 11_700_000, delta=1_000)

    def test_dolares_aplica_factor_cambio(self):
        resultado = _parsear_fee("$10K")
        self.assertAlmostEqual(resultado, 9_200, delta=100)

    def test_free_devuelve_none(self):
        self.assertIsNone(_parsear_fee("Free"))

    def test_loan_devuelve_none(self):
        self.assertIsNone(_parsear_fee("Loan"))

    def test_guion_devuelve_none(self):
        self.assertIsNone(_parsear_fee("-"))

    def test_na_devuelve_none(self):
        self.assertIsNone(_parsear_fee("n/a"))

    def test_none_devuelve_none(self):
        self.assertIsNone(_parsear_fee(None))

    def test_cadena_vacia_devuelve_none(self):
        self.assertIsNone(_parsear_fee(""))

    def test_valor_no_numerico_devuelve_none(self):
        self.assertIsNone(_parsear_fee("€abc"))

    def test_case_insensitive_multiplicador(self):
        """El sufijo M/K debe funcionar en minúsculas también."""
        self.assertAlmostEqual(_parsear_fee("€5m"), 5_000_000, places=0)


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tests de analizar_valor_plantilla 
#    En esta función implementamos toda la lógica de negocio (Pandas + cruce de datos)
#    y equivale al "modelo" del caso de uso, ya que en plantilla/models.py
#    no definimos modelos propios.
# ──────────────────────────────────────────────────────────────────────────────

class AnalizarValorPlantillaTests(TestCase):
    """
    Tests del núcleo del caso de uso F3.

    Validamos:
      · Estructura del resultado
      · Uso correcto de fees reales vs. valores de fallback por posición
      · Conteo de jugadores con fee confirmado
      · Coherencia matemática del total
      · Aggregations de Pandas (groupby + agg)
      · Normalización de posiciones desconocidas o nulas
      · Traducciones español de posición
    """

    # ── Casos de error ──────────────────────────────────────────────────────

    def test_lista_vacia_devuelve_clave_error(self):
        resultado = analizar_valor_plantilla([], {})
        self.assertIn("error", resultado)

    # ── Estructura del resultado ────────────────────────────────────────────

    def test_claves_obligatorias_presentes(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        for clave in ("resumen", "tabla", "total_plantilla", "num_jugadores", "jugadores_con_fee"):
            with self.subTest(clave=clave):
                self.assertIn(clave, resultado)

    def test_num_jugadores_correcto(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        self.assertEqual(resultado["num_jugadores"], len(JUGADORES_MUESTRA))

    # ── Fallback por posición cuando no hay fees ────────────────────────────

    def test_sin_fees_jugadores_con_fee_es_cero(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        self.assertEqual(resultado["jugadores_con_fee"], 0)

    def test_sin_fees_usa_valor_fallback_por_posicion(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        for fila in resultado["tabla"]:
            pos_api  = fila["posicion"]
            expected = float(VALOR_FALLBACK.get(pos_api, VALOR_FALLBACK["Midfielder"]))
            with self.subTest(jugador=fila["nombre"]):
                self.assertAlmostEqual(fila["valor_euros"], expected, places=0)

    def test_sin_fees_fuente_es_estimado(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        for fila in resultado["tabla"]:
            with self.subTest(jugador=fila["nombre"]):
                self.assertEqual(fila["fuente"], "Estimado")

    # ── Cruce con fees de transferencia reales ──────────────────────────────

    def test_con_fee_real_valor_coincide(self):
        resultado  = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        tabla_dict = {j["id"]: j for j in resultado["tabla"]}

        self.assertAlmostEqual(tabla_dict["3"]["valor_euros"], 3_000_000, places=0)
        self.assertAlmostEqual(tabla_dict["4"]["valor_euros"], 1_500_000, places=0)

    def test_con_fee_real_fuente_es_transferencia(self):
        resultado  = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        tabla_dict = {j["id"]: j for j in resultado["tabla"]}

        self.assertEqual(tabla_dict["3"]["fuente"], "Transferencia")
        self.assertEqual(tabla_dict["4"]["fuente"], "Transferencia")

    def test_sin_fee_en_jugador_individual_sigue_usando_fallback(self):
        resultado  = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        tabla_dict = {j["id"]: j for j in resultado["tabla"]}

        # Fabri (id=1) no tiene fee → fallback Goalkeeper
        self.assertEqual(tabla_dict["1"]["fuente"], "Estimado")
        self.assertAlmostEqual(
            tabla_dict["1"]["valor_euros"],
            float(VALOR_FALLBACK["Goalkeeper"]),
            places=0,
        )

    def test_jugadores_con_fee_cuenta_correctamente(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        self.assertEqual(resultado["jugadores_con_fee"], len(FEES_MUESTRA))

    # ── Coherencia matemática ───────────────────────────────────────────────

    def test_total_plantilla_es_suma_de_tabla(self):
        resultado  = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        suma_tabla = sum(j["valor_euros"] for j in resultado["tabla"])
        self.assertAlmostEqual(resultado["total_plantilla"], suma_tabla, places=0)

    def test_total_plantilla_con_fees_es_suma_de_tabla(self):
        resultado  = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        suma_tabla = sum(j["valor_euros"] for j in resultado["tabla"])
        self.assertAlmostEqual(resultado["total_plantilla"], suma_tabla, places=0)

    # ── Aggregations de Pandas (groupby) ────────────────────────────────────

    def test_resumen_una_posicion_agrega_un_jugador(self):
        """Sólo Goalkeeper en la muestra → resumen con 1 fila y 1 jugador."""
        solo_portero = [JUGADORES_MUESTRA[0]]  
        resultado    = analizar_valor_plantilla(solo_portero, {})
        self.assertEqual(len(resultado["resumen"]), 1)
        self.assertEqual(resultado["resumen"][0]["jugadores"], 1)
        self.assertAlmostEqual(
            resultado["resumen"][0]["valor_total"],
            float(VALOR_FALLBACK["Goalkeeper"]),
            places=0,
        )

    def test_resumen_con_dos_posiciones(self):
        dos_posiciones = [JUGADORES_MUESTRA[0], JUGADORES_MUESTRA[1]]   # GK + DEF
        resultado = analizar_valor_plantilla(dos_posiciones, {})
        self.assertEqual(len(resultado["resumen"]), 2)

    def test_resumen_contiene_posicion_portero(self):
        resultado       = analizar_valor_plantilla(JUGADORES_MUESTRA, {})
        posiciones_es   = {r["posicion_es"] for r in resultado["resumen"]}
        self.assertIn("Portero", posiciones_es)

    def test_resumen_con_fee_cuenta_con_fee_real(self):
        resultado = analizar_valor_plantilla(JUGADORES_MUESTRA, FEES_MUESTRA)
        resumen_d = {r["posicion_es"]: r for r in resultado["resumen"]}
        # Delanteros: jugadores 3 y 5; sólo 3 tiene fee real → con_fee_real == 1
        self.assertEqual(resumen_d["Delantero"]["con_fee_real"], 1)
        # Centrocampistas: jugador 4 tiene fee real → con_fee_real == 1
        self.assertEqual(resumen_d["Centrocampista"]["con_fee_real"], 1)
        # Porteros: ningún fee → con_fee_real == 0
        self.assertEqual(resumen_d["Portero"]["con_fee_real"], 0)

    # ── Normalización de posiciones desconocidas ────────────────────────────

    def test_posicion_desconocida_usa_midfielder_fallback(self):
        jugador_raro = [
            {"id": "99", "nombre": "X", "edad": 22, "foto": "", "numero": 99, "posicion": "Coach"}
        ]
        resultado = analizar_valor_plantilla(jugador_raro, {})
        self.assertAlmostEqual(
            resultado["tabla"][0]["valor_euros"],
            float(VALOR_FALLBACK["Midfielder"]),
            places=0,
        )

    def test_posicion_none_usa_midfielder_fallback(self):
        jugador_none = [
            {"id": "99", "nombre": "Y", "edad": 22, "foto": "", "numero": 99, "posicion": None}
        ]
        resultado = analizar_valor_plantilla(jugador_none, {})
        self.assertAlmostEqual(
            resultado["tabla"][0]["valor_euros"],
            float(VALOR_FALLBACK["Midfielder"]),
            places=0,
        )

    # ── Traducción de posición al español ───────────────────────────────────

    def test_posicion_es_portero(self):
        solo_portero = [JUGADORES_MUESTRA[0]]
        resultado    = analizar_valor_plantilla(solo_portero, {})
        self.assertEqual(resultado["tabla"][0]["posicion_es"], "Portero")

    def test_posicion_es_delantero(self):
        solo_delantero = [JUGADORES_MUESTRA[2]]
        resultado      = analizar_valor_plantilla(solo_delantero, {})
        self.assertEqual(resultado["tabla"][0]["posicion_es"], "Delantero")

    def test_posicion_es_defensa(self):
        solo_defensa = [JUGADORES_MUESTRA[1]]
        resultado    = analizar_valor_plantilla(solo_defensa, {})
        self.assertEqual(resultado["tabla"][0]["posicion_es"], "Defensa")

    def test_posicion_es_centrocampista(self):
        solo_medio = [JUGADORES_MUESTRA[3]]
        resultado  = analizar_valor_plantilla(solo_medio, {})
        self.assertEqual(resultado["tabla"][0]["posicion_es"], "Centrocampista")


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tests de buscar_equipos  (mocking de GET /teams)
# ──────────────────────────────────────────────────────────────────────────────

class BuscarEquiposTests(TestCase):
    """Valida buscar_equipos mockeando requests.get."""

    # ── Helper ──────────────────────────────────────────────────────────────

    @staticmethod
    def _mock_ok(payload):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = payload
        return m

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_busqueda_exitosa_devuelve_lista(self, mock_get):
        mock_get.return_value = self._mock_ok({
            "errors": {},
            "response": [{"team": {"id": 558, "name": "RC Deportivo", "country": "Spain", "logo": ""}}],
        })
        resultado = buscar_equipos("Deportivo")
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["id"], "558")
        self.assertEqual(resultado[0]["nombre"], "RC Deportivo")

    @patch("plantilla.services.requests.get")
    def test_busqueda_vacia_devuelve_lista_vacia(self, mock_get):
        mock_get.return_value = self._mock_ok({"errors": {}, "response": []})
        self.assertEqual(buscar_equipos("xxxxxx"), [])

    @patch("plantilla.services.requests.get")
    def test_filtra_equipos_sin_id(self, mock_get):
        """Equipos con id=None deben excluirse del resultado."""
        mock_get.return_value = self._mock_ok({
            "errors": {},
            "response": [
                {"team": {"id": None, "name": "Sin ID",      "country": "Spain", "logo": ""}},
                {"team": {"id": 558,  "name": "RC Deportivo", "country": "Spain", "logo": ""}},
            ],
        })
        resultado = buscar_equipos("Deportivo")
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["id"], "558")

    # ── Errores de la API ────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_error_limite_peticiones_lanza_runtime(self, mock_get):
        mock_get.return_value = self._mock_ok({
            "errors": {"requests": "Reached the request limit per day."},
            "response": [],
        })
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Deportivo")
        self.assertIn("límite diario", str(ctx.exception))

    @patch("plantilla.services.requests.get")
    def test_error_generico_api_lanza_runtime(self, mock_get):
        mock_get.return_value = self._mock_ok({
            "errors": {"token": "Error: invalid api key"},
            "response": [],
        })
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Deportivo")
        self.assertIn("API-Football", str(ctx.exception))

    # ── Errores de red / HTTP ────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_timeout_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Deportivo")
        self.assertIn("tardó demasiado", str(ctx.exception))

    @patch("plantilla.services.requests.get")
    def test_http_401_lanza_runtime_con_mensaje_clave(self, mock_get):
        resp_mock = MagicMock()
        resp_mock.status_code = 401
        http_error = _requests_module.exceptions.HTTPError(response=resp_mock)
        m = MagicMock()
        m.raise_for_status.side_effect = http_error
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            buscar_equipos("Deportivo")
        self.assertIn("401", str(ctx.exception))

    @patch("plantilla.services.requests.get")
    def test_conexion_rechazada_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError("refused")
        with self.assertRaises(RuntimeError):
            buscar_equipos("Deportivo")


# ──────────────────────────────────────────────────────────────────────────────
# 5. Tests de obtener_plantilla  (mocking de GET /players con paginación)
# ──────────────────────────────────────────────────────────────────────────────

class ObtenerPlantillaTests(TestCase):
    """Valida obtener_plantilla mockeando la paginación de /players."""

    @staticmethod
    def _entry(pid, name, position="Midfielder"):
        return {
            "player":     {"id": pid, "name": name, "age": 25, "photo": ""},
            "statistics": [{"games": {"position": position, "number": pid}}],
        }

    @staticmethod
    def _mock_page(entries, page=1, total=1):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = {
            "response": entries,
            "paging":   {"current": page, "total": total},
        }
        return m

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_plantilla_basica_una_pagina(self, mock_get):
        mock_get.return_value = self._mock_page([self._entry(1, "Fabri", "Goalkeeper")])
        resultado = obtener_plantilla("558")
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["nombre"], "Fabri")
        self.assertEqual(resultado[0]["posicion"], "Goalkeeper")

    @patch("plantilla.services.requests.get")
    def test_paginacion_recoge_todas_las_paginas(self, mock_get):
        """Con 2 páginas, la función debe devolver jugadores de ambas."""
        mock_get.side_effect = [
            self._mock_page([self._entry(1, "Fabri")], page=1, total=2),
            self._mock_page([self._entry(2, "Ximo")],  page=2, total=2),
        ]
        resultado = obtener_plantilla("558")
        self.assertEqual(len(resultado), 2)
        nombres = {j["nombre"] for j in resultado}
        self.assertIn("Fabri", nombres)
        self.assertIn("Ximo",  nombres)

    @patch("plantilla.services.requests.get")
    def test_temporada_vacia_reintenta_con_anterior(self, mock_get):
        """
        Si /players devuelve vacío para la temporada actual (page=1),
        la función debe reintentar con CURRENT_SEASON - 1.
        """
        mock_get.side_effect = [
            self._mock_page([]),                              # temporada actual → vacía
            self._mock_page([self._entry(1, "Fabri")]),       # temporada anterior → datos
        ]
        resultado = obtener_plantilla("558", season=CURRENT_SEASON)
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["nombre"], "Fabri")
        # Verificamos que se hizo la segunda llamada con la temporada anterior
        llamadas = mock_get.call_args_list
        self.assertEqual(len(llamadas), 2)
        temporada_segunda_llamada = llamadas[1][1]["params"]["season"]
        self.assertEqual(temporada_segunda_llamada, CURRENT_SEASON - 1)

    # ── Normalización de datos ──────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_posicion_none_se_normaliza_a_midfielder(self, mock_get):
        entry = {
            "player":     {"id": 99, "name": "X", "age": 22, "photo": ""},
            "statistics": [{"games": {"position": None, "number": 99}}],
        }
        mock_get.return_value = self._mock_page([entry])
        resultado = obtener_plantilla("558")
        self.assertEqual(resultado[0]["posicion"], "Midfielder")

    # ── Errores de red ──────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_timeout_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError) as ctx:
            obtener_plantilla("558")
        self.assertIn("tardó demasiado", str(ctx.exception))

    @patch("plantilla.services.requests.get")
    def test_http_500_lanza_runtime_con_codigo(self, mock_get):
        resp_mock = MagicMock()
        resp_mock.status_code = 500
        http_error = _requests_module.exceptions.HTTPError(response=resp_mock)
        m = MagicMock()
        m.raise_for_status.side_effect = http_error
        mock_get.return_value = m
        with self.assertRaises(RuntimeError) as ctx:
            obtener_plantilla("558")
        self.assertIn("500", str(ctx.exception))


# ──────────────────────────────────────────────────────────────────────────────
# 6. Tests de obtener_fees_transferencias  (mocking de GET /transfers)
# ──────────────────────────────────────────────────────────────────────────────

class ObtenerFeesTests(TestCase):
    """
    Valida obtener_fees_transferencias.
    Característica clave: falla silenciosamente (devuelve {}) ante cualquier error.
    """

    @staticmethod
    def _entry(player_id, transfers):
        return {"player": {"id": player_id}, "transfers": transfers}

    @staticmethod
    def _transfer(date, fee_str, team_in_id, team_out_id=100):
        return {
            "date":  date,
            "type":  fee_str,
            "teams": {"in": {"id": team_in_id}, "out": {"id": team_out_id}},
        }

    @staticmethod
    def _mock_ok(entries):
        m = MagicMock()
        m.raise_for_status = MagicMock()
        m.json.return_value = {"response": entries}
        return m

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_fee_de_entrada_detectado(self, mock_get):
        entry = self._entry(10, [self._transfer("2023-07-01", "€5M", team_in_id=558)])
        mock_get.return_value = self._mock_ok([entry])
        fees = obtener_fees_transferencias("558")
        self.assertIn("10", fees)
        self.assertAlmostEqual(fees["10"], 5_000_000, places=0)

    @patch("plantilla.services.requests.get")
    def test_transferencia_free_no_genera_fee(self, mock_get):
        entry = self._entry(10, [self._transfer("2023-07-01", "Free", team_in_id=558)])
        mock_get.return_value = self._mock_ok([entry])
        fees = obtener_fees_transferencias("558")
        self.assertNotIn("10", fees)

    @patch("plantilla.services.requests.get")
    def test_multiples_jugadores(self, mock_get):
        entries = [
            self._entry(10, [self._transfer("2023-07-01", "€3M",   team_in_id=558)]),
            self._entry(11, [self._transfer("2023-07-01", "€1.5M", team_in_id=558)]),
        ]
        mock_get.return_value = self._mock_ok(entries)
        fees = obtener_fees_transferencias("558")
        self.assertEqual(len(fees), 2)
        self.assertAlmostEqual(fees["10"], 3_000_000, places=0)
        self.assertAlmostEqual(fees["11"], 1_500_000, places=0)

    @patch("plantilla.services.requests.get")
    def test_usa_transferencia_mas_reciente_de_entrada(self, mock_get):
        """Con varias entradas al equipo, usa la más reciente (orden descendente)."""
        entry = self._entry(10, [
            self._transfer("2021-07-01", "€1M", team_in_id=558),
            self._transfer("2023-07-01", "€5M", team_in_id=558),
        ])
        mock_get.return_value = self._mock_ok([entry])
        fees = obtener_fees_transferencias("558")
        self.assertAlmostEqual(fees["10"], 5_000_000, places=0)

    # ── Fallo silencioso ────────────────────────────────────────────────────

    @patch("plantilla.services.requests.get")
    def test_error_de_red_devuelve_dict_vacio(self, mock_get):
        mock_get.side_effect = Exception("network error")
        fees = obtener_fees_transferencias("558")
        self.assertEqual(fees, {})

    @patch("plantilla.services.requests.get")
    def test_timeout_devuelve_dict_vacio(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        fees = obtener_fees_transferencias("558")
        self.assertEqual(fees, {})


# ──────────────────────────────────────────────────────────────────────────────
# 7. Tests de la vista valor_mercado
# ──────────────────────────────────────────────────────────────────────────────

class ValorMercadoViewTests(TestCase):
    """
    Tests HTTP de la vista valor_mercado.

    Cubre autenticación, GET inicial y las distintas ramas del POST:
      · sin nombre → mensaje de error
      · team_id directo → carga de plantilla
      · búsqueda sin resultados → aviso
      · múltiples candidatos → selector
      · candidato exacto → carga directa sin selector
      · único candidato → carga directa sin selector
      · RuntimeError en búsqueda → mensaje de error
      · plantilla vacía → aviso
    """

    def setUp(self):
        self.client = Client()
        self.user   = User.objects.create_user(username="testuser", password="testpass")
        self.url    = reverse("plantilla:valor_mercado")

    # ── Autenticación ────────────────────────────────────────────────────────

    def test_get_sin_login_redirige(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_sin_login_redirige(self):
        response = self.client.post(self.url, {"equipo": "Deportivo"})
        self.assertEqual(response.status_code, 302)

    # ── GET autenticado ──────────────────────────────────────────────────────

    def test_get_renderiza_plantilla_html(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "plantilla/valor_mercado.html")

    def test_get_contexto_inicial_correcto(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertIsNone(response.context["resultado"])
        self.assertIsNone(response.context["candidatos"])
        self.assertIn("equipos_sugeridos", response.context)

    # ── POST sin nombre ──────────────────────────────────────────────────────

    def test_post_sin_nombre_muestra_mensaje_error(self):
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "", "team_id": ""})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m) for m in response.context["messages"]]
        self.assertTrue(any("Introduce" in m for m in msgs))

    # ── POST con team_id directo ─────────────────────────────────────────────

    @patch("plantilla.views.analizar_valor_plantilla")
    @patch("plantilla.views.obtener_fees_transferencias")
    @patch("plantilla.views.obtener_plantilla")
    @patch("plantilla.views.obtener_info_equipo")
    def test_post_team_id_carga_resultado(
        self, mock_info, mock_plantilla, mock_fees, mock_analizar
    ):
        mock_info.return_value     = {"nombre": "RC Deportivo", "logo": "", "pais": "Spain"}
        mock_plantilla.return_value = JUGADORES_MUESTRA
        mock_fees.return_value     = {}
        mock_analizar.return_value = {
            "resumen": [], "tabla": [], "total_plantilla": 0,
            "num_jugadores": 5, "jugadores_con_fee": 0,
        }
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "RC Deportivo", "team_id": "558"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["resultado"])

    @patch("plantilla.views.obtener_plantilla")
    @patch("plantilla.views.obtener_info_equipo")
    def test_post_team_id_plantilla_vacia_muestra_aviso(self, mock_info, mock_plantilla):
        mock_info.return_value      = {"nombre": "RC Deportivo", "logo": "", "pais": "Spain"}
        mock_plantilla.return_value = []
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "RC Deportivo", "team_id": "558"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("jugadores" in m for m in msgs))

    # ── POST con búsqueda por nombre ─────────────────────────────────────────

    @patch("plantilla.views.buscar_equipos")
    def test_post_sin_resultados_muestra_aviso(self, mock_buscar):
        mock_buscar.return_value = []
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "EquipoInexistente"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("encontrado" in m for m in msgs))

    @patch("plantilla.views.buscar_equipos")
    def test_post_multiples_candidatos_muestra_selector(self, mock_buscar):
        mock_buscar.return_value = CANDIDATOS_MUESTRA   # 2 candidatos, sin coincidencia exacta
        self.client.login(username="testuser", password="testpass")
        # Usamos un nombre que NO coincide exactamente con ningún candidato
        response = self.client.post(self.url, {"equipo": "Deportivo"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.context["candidatos"])
        self.assertIsNone(response.context["resultado"])

    @patch("plantilla.views.analizar_valor_plantilla")
    @patch("plantilla.views.obtener_fees_transferencias")
    @patch("plantilla.views.obtener_plantilla")
    @patch("plantilla.views.obtener_info_equipo")
    @patch("plantilla.views.buscar_equipos")
    def test_post_candidato_exacto_carga_sin_mostrar_selector(
        self, mock_buscar, mock_info, mock_plantilla, mock_fees, mock_analizar
    ):
        """
        Si la búsqueda devuelve varios candidatos pero uno coincide exactamente
        con el nombre introducido, debe cargarse directamente sin mostrar el selector.
        """
        mock_buscar.return_value    = CANDIDATOS_MUESTRA   # 2 candidatos
        mock_info.return_value      = {"nombre": "RC Deportivo de La Coruña", "logo": "", "pais": "Spain"}
        mock_plantilla.return_value = JUGADORES_MUESTRA
        mock_fees.return_value      = {}
        mock_analizar.return_value  = {
            "resumen": [], "tabla": [], "total_plantilla": 0,
            "num_jugadores": 5, "jugadores_con_fee": 0,
        }
        self.client.login(username="testuser", password="testpass")
        # Nombre exacto del primer candidato → elegir_candidato_por_nombre lo encuentra
        response = self.client.post(self.url, {"equipo": "RC Deportivo de La Coruña"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["candidatos"])     # No debe aparecer el selector
        self.assertIsNotNone(response.context["resultado"])   # Debe mostrar resultado

    @patch("plantilla.views.analizar_valor_plantilla")
    @patch("plantilla.views.obtener_fees_transferencias")
    @patch("plantilla.views.obtener_plantilla")
    @patch("plantilla.views.obtener_info_equipo")
    @patch("plantilla.views.buscar_equipos")
    def test_post_unico_candidato_carga_directamente(
        self, mock_buscar, mock_info, mock_plantilla, mock_fees, mock_analizar
    ):
        """Con un único candidato en la búsqueda, debe cargarse sin pasar por el selector."""
        mock_buscar.return_value    = [CANDIDATOS_MUESTRA[0]]   # 1 solo resultado
        mock_info.return_value      = {"nombre": "RC Deportivo de La Coruña", "logo": "", "pais": "Spain"}
        mock_plantilla.return_value = JUGADORES_MUESTRA
        mock_fees.return_value      = {}
        mock_analizar.return_value  = {
            "resumen": [], "tabla": [], "total_plantilla": 0,
            "num_jugadores": 5, "jugadores_con_fee": 0,
        }
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "Deportivo La Coruña"})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["candidatos"])
        self.assertIsNotNone(response.context["resultado"])

    @patch("plantilla.views.buscar_equipos")
    def test_post_runtime_error_muestra_mensaje_al_usuario(self, mock_buscar):
        mock_buscar.side_effect = RuntimeError("límite diario de peticiones alcanzado")
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"equipo": "Deportivo"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("límite" in m for m in msgs))


# ──────────────────────────────────────────────────────────────────────────────
# 8. Tests del endpoint de autocompletado
# ──────────────────────────────────────────────────────────────────────────────

class AutocompleteViewTests(TestCase):
    """Tests para la vista autocomplete_equipos (JSON, GET-only, login_required)."""

    def setUp(self):
        self.client = Client()
        self.user   = User.objects.create_user(username="autouser", password="testpass")
        self.url    = reverse("plantilla:autocomplete")

    # ── Autenticación ────────────────────────────────────────────────────────

    def test_sin_login_redirige(self):
        response = self.client.get(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 302)

    # ── Validación de longitud de query ─────────────────────────────────────

    def test_query_vacia_devuelve_sugerencias_vacias(self):
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sugerencias"], [])

    def test_query_un_caracter_devuelve_sugerencias_vacias(self):
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "D"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sugerencias"], [])

    # ── Respuesta correcta ───────────────────────────────────────────────────

    @patch("plantilla.views.buscar_equipos")
    def test_query_valida_devuelve_sugerencias_con_claves(self, mock_buscar):
        mock_buscar.return_value = CANDIDATOS_MUESTRA
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("sugerencias", data)
        self.assertEqual(len(data["sugerencias"]), len(CANDIDATOS_MUESTRA))
        primera = data["sugerencias"][0]
        for clave in ("label", "id", "pais", "logo"):
            with self.subTest(clave=clave):
                self.assertIn(clave, primera)

    @patch("plantilla.views.buscar_equipos")
    def test_no_devuelve_mas_de_8_sugerencias(self, mock_buscar):
        """El endpoint limita las sugerencias a 8."""
        mock_buscar.return_value = [
            {"id": str(i), "nombre": f"Club {i}", "pais": "Spain", "logo": ""}
            for i in range(20)
        ]
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "Club"})
        self.assertLessEqual(len(response.json()["sugerencias"]), 8)

    # ── Robustez ─────────────────────────────────────────────────────────────

    @patch("plantilla.views.buscar_equipos")
    def test_excepcion_interna_devuelve_lista_vacia_sin_500(self, mock_buscar):
        """Si buscar_equipos falla, el endpoint devuelve [] con HTTP 200 (no 500)."""
        mock_buscar.side_effect = Exception("unexpected failure")
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["sugerencias"], [])

    def test_metodo_post_devuelve_405(self):
        """La vista está decorada con @require_GET → POST debe devolver 405."""
        self.client.login(username="autouser", password="testpass")
        response = self.client.post(self.url, {"q": "Dep"})
        self.assertEqual(response.status_code, 405)

