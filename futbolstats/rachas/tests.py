"""
rachas/tests.py
===============
Suite de tests para F2 — Comparador de rachas y clasificación.

Estructura
----------
  ObtenerClasificacionTests       — GET /standings mockeado con @patch
  ObtenerResultadosTemporadaTests — GET /matches mockeado con @patch
  CalcularRankingFormaTests       — lógica Pandas pura: el «modelo» del caso de uso  ← OBLIGATORIO (rúbrica)
  ComparadorViewTests             — vistas HTTP: login, GET, POST (múltiples ramas)
  AutocompleteCompeticionesTests  — endpoint JSON de autocompletado
"""

import math
from unittest.mock import patch, MagicMock

import requests as _requests_module   # para usar las clases de excepción en side_effect

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User

from rachas.services import (
    COMPETICIONES,
    COMPETICION_DEFAULT,
    obtener_clasificacion_oficial,
    obtener_resultados_temporada,
    calcular_ranking_forma,
)


# ──────────────────────────────────────────────────────────────────────────────
# Datos de muestra compartidos
# ──────────────────────────────────────────────────────────────────────────────

def _partido(home, away, g_l, g_v, fecha):
    """Construye un dict de partido con la misma estructura que devuelve football-data.org."""
    return {
        "homeTeam": {"name": home},
        "awayTeam": {"name": away},
        "score":    {"fullTime": {"home": g_l, "away": g_v}},
        "utcDate":  f"{fecha}T20:00:00Z",
    }


# Clasificación de muestra (dos equipos)
CLASIFICACION_MUESTRA = [
    {
        "pos": 1, "equipo": "Real Madrid",  "puntos": 75,
        "pg": 24, "pe": 3, "pp": 3, "gf": 65, "gc": 20, "dg": 45, "pj": 30,
    },
    {
        "pos": 2, "equipo": "FC Barcelona", "puntos": 70,
        "pg": 22, "pe": 4, "pp": 4, "gf": 60, "gc": 25, "dg": 35, "pj": 30,
    },
]

# Ranking de forma de muestra
RANKING_MUESTRA = [
    {
        "equipo": "FC Barcelona", "racha_pts": 12, "partidos_racha": 4,
        "racha_lista": ["V", "V", "V", "V"], "pos_racha": 1, "pos": 2, "delta_pos": 1,
    },
    {
        "equipo": "Real Madrid",  "racha_pts": 9,  "partidos_racha": 4,
        "racha_lista": ["V", "V", "V", "E"], "pos_racha": 2, "pos": 1, "delta_pos": -1,
    },
]

# Payload de standings de la API
STANDINGS_PAYLOAD = {
    "standings": [
        {
            "type": "TOTAL",
            "table": [
                {
                    "position": 1, "team": {"name": "Real Madrid"},
                    "points": 75, "won": 24, "draw": 3, "lost": 3,
                    "goalsFor": 65, "goalsAgainst": 20, "goalDifference": 45,
                    "playedGames": 30,
                },
                {
                    "position": 2, "team": {"name": "FC Barcelona"},
                    "points": 70, "won": 22, "draw": 4, "lost": 4,
                    "goalsFor": 60, "goalsAgainst": 25, "goalDifference": 35,
                    "playedGames": 30,
                },
            ],
        }
    ]
}

# Helpers para mocks HTTP
def _mock_respuesta_ok(payload):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = payload
    return m


def _mock_http_error(codigo):
    resp = MagicMock()
    resp.status_code = codigo
    m = MagicMock()
    m.raise_for_status.side_effect = _requests_module.exceptions.HTTPError(response=resp)
    return m


# ──────────────────────────────────────────────────────────────────────────────
# 1. Tests de obtener_clasificacion_oficial  (mocking de GET /standings)
# ──────────────────────────────────────────────────────────────────────────────

class ObtenerClasificacionTests(TestCase):
    """Valida obtener_clasificacion_oficial mockeando requests.get."""

    # ── Happy path ──────────────────────────────────────────────────────────

    @patch("rachas.services.requests.get")
    def test_clasificacion_basica_devuelve_lista(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok(STANDINGS_PAYLOAD)
        resultado = obtener_clasificacion_oficial("PD")
        self.assertIsInstance(resultado, list)
        self.assertEqual(len(resultado), 2)

    @patch("rachas.services.requests.get")
    def test_primera_fila_tiene_pos_1(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok(STANDINGS_PAYLOAD)
        resultado = obtener_clasificacion_oficial("PD")
        self.assertEqual(resultado[0]["pos"], 1)
        self.assertEqual(resultado[0]["equipo"], "Real Madrid")

    @patch("rachas.services.requests.get")
    def test_estructura_fila_tiene_claves_obligatorias(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok(STANDINGS_PAYLOAD)
        resultado = obtener_clasificacion_oficial("PD")
        claves = {"pos", "equipo", "puntos", "pg", "pe", "pp", "gf", "gc", "dg", "pj"}
        for clave in claves:
            with self.subTest(clave=clave):
                self.assertIn(clave, resultado[0])

    @patch("rachas.services.requests.get")
    def test_selecciona_tipo_total_si_hay_varios_tipos(self, mock_get):
        """Cuando hay varios standings (HOME, AWAY, TOTAL), debe usar TOTAL."""
        payload = {
            "standings": [
                {"type": "HOME",  "table": [{"position": 1, "team": {"name": "X"}, "points": 10,
                  "won": 3, "draw": 1, "lost": 0, "goalsFor": 8, "goalsAgainst": 2,
                  "goalDifference": 6, "playedGames": 4}]},
                {"type": "AWAY",  "table": []},
                {"type": "TOTAL", "table": [{"position": 1, "team": {"name": "Real Madrid"},
                  "points": 75, "won": 24, "draw": 3, "lost": 3, "goalsFor": 65,
                  "goalsAgainst": 20, "goalDifference": 45, "playedGames": 30}]},
            ]
        }
        mock_get.return_value = _mock_respuesta_ok(payload)
        resultado = obtener_clasificacion_oficial("PD")
        self.assertEqual(resultado[0]["equipo"], "Real Madrid")

    @patch("rachas.services.requests.get")
    def test_standings_vacio_devuelve_lista_vacia(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok({"standings": []})
        resultado = obtener_clasificacion_oficial("PD")
        self.assertEqual(resultado, [])

    @patch("rachas.services.requests.get")
    def test_tabla_interna_vacia_devuelve_lista_vacia(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok({"standings": [{"type": "TOTAL", "table": []}]})
        resultado = obtener_clasificacion_oficial("PD")
        self.assertEqual(resultado, [])

    # ── Errores HTTP ─────────────────────────────────────────────────────────

    @patch("rachas.services.requests.get")
    def test_http_403_lanza_runtime_con_mensaje_token(self, mock_get):
        mock_get.return_value = _mock_http_error(403)
        with self.assertRaises(RuntimeError) as ctx:
            obtener_clasificacion_oficial("PD")
        self.assertIn("403", str(ctx.exception))

    @patch("rachas.services.requests.get")
    def test_http_429_lanza_runtime_limite_peticiones(self, mock_get):
        mock_get.return_value = _mock_http_error(429)
        with self.assertRaises(RuntimeError) as ctx:
            obtener_clasificacion_oficial("PD")
        self.assertIn("límite", str(ctx.exception))

    @patch("rachas.services.requests.get")
    def test_http_generico_lanza_runtime_con_codigo(self, mock_get):
        mock_get.return_value = _mock_http_error(500)
        with self.assertRaises(RuntimeError) as ctx:
            obtener_clasificacion_oficial("PD")
        self.assertIn("500", str(ctx.exception))

    @patch("rachas.services.requests.get")
    def test_request_exception_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.ConnectionError("refused")
        with self.assertRaises(RuntimeError):
            obtener_clasificacion_oficial("PD")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Tests de obtener_resultados_temporada  (mocking de GET /matches)
# ──────────────────────────────────────────────────────────────────────────────

class ObtenerResultadosTemporadaTests(TestCase):
    """Valida obtener_resultados_temporada mockeando requests.get."""

    @patch("rachas.services.requests.get")
    def test_resultados_ok_devuelve_lista_de_partidos(self, mock_get):
        partidos = [_partido("Real Madrid", "FC Barcelona", 2, 1, "2024-01-15")]
        mock_get.return_value = _mock_respuesta_ok({"matches": partidos})
        resultado = obtener_resultados_temporada("PD")
        self.assertEqual(len(resultado), 1)
        self.assertEqual(resultado[0]["homeTeam"]["name"], "Real Madrid")

    @patch("rachas.services.requests.get")
    def test_lista_vacia_si_no_hay_partidos(self, mock_get):
        mock_get.return_value = _mock_respuesta_ok({"matches": []})
        self.assertEqual(obtener_resultados_temporada("PD"), [])

    @patch("rachas.services.requests.get")
    def test_http_429_lanza_runtime(self, mock_get):
        mock_get.return_value = _mock_http_error(429)
        with self.assertRaises(RuntimeError) as ctx:
            obtener_resultados_temporada("PD")
        self.assertIn("límite", str(ctx.exception))

    @patch("rachas.services.requests.get")
    def test_http_generico_lanza_runtime_con_codigo(self, mock_get):
        mock_get.return_value = _mock_http_error(503)
        with self.assertRaises(RuntimeError) as ctx:
            obtener_resultados_temporada("PD")
        self.assertIn("503", str(ctx.exception))

    @patch("rachas.services.requests.get")
    def test_request_exception_lanza_runtime(self, mock_get):
        mock_get.side_effect = _requests_module.exceptions.Timeout()
        with self.assertRaises(RuntimeError):
            obtener_resultados_temporada("PD")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Tests de calcular_ranking_forma  ← OBLIGATORIO según rúbrica
#    Esta función implementa toda la lógica de negocio con Pandas y es
#    el equivalente al «modelo» del caso de uso, dado que rachas/models.py
#    no define modelos propios (datos en tiempo real de la API).
# ──────────────────────────────────────────────────────────────────────────────

class CalcularRankingFormaTests(TestCase):
    """
    Tests del núcleo del caso de uso F2.

    Valida:
      · Manejo de lista vacía y scores nulos
      · Asignación de puntos y strings de resultado (V/E/D) por tipo de marcador
      · Estructura y claves del resultado
      · Ordenación descendente por racha_pts
      · Posición pos_racha correlativa desde 1
      · Efecto real de n_partidos (ventana cronológica)
      · Contenido y orden cronológico de racha_lista
      · Conteo de partidos en la ventana (partidos_racha)
      · Cálculo de delta_pos con y sin clasificacion_oficial
      · Casos edge: equipo sin clasificación oficial, delta_pos cero
    """

    # ── Casos vacíos y datos inválidos ─────────────────────────────────────

    def test_lista_vacia_devuelve_lista_vacia(self):
        self.assertEqual(calcular_ranking_forma([], 5), [])

    def test_scores_none_se_ignoran_y_no_rompen(self):
        """Partidos con score None deben descartarse silenciosamente."""
        partidos = [{
            "homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
            "score":    {"fullTime": {"home": None, "away": None}},
            "utcDate":  "2024-01-01T20:00:00Z",
        }]
        resultado = calcular_ranking_forma(partidos, 5)
        # Todo el partido se ignora → sin filas → lista vacía
        self.assertEqual(resultado, [])

    def test_solo_scores_none_devuelve_lista_vacia(self):
        """Sólo partidos con score None → filas vacías → resultado vacío."""
        partidos = [
            {"homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
             "score": {"fullTime": {"home": None, "away": 1}}, "utcDate": "2024-01-01T20:00:00Z"},
            {"homeTeam": {"name": "A"}, "awayTeam": {"name": "B"},
             "score": {"fullTime": {"home": 2, "away": None}}, "utcDate": "2024-01-08T20:00:00Z"},
        ]
        self.assertEqual(calcular_ranking_forma(partidos, 5), [])

    # ── Asignación de puntos ────────────────────────────────────────────────

    def test_victoria_local_tres_puntos_local_cero_visitante(self):
        """Home win → local 3 pts, visitante 0 pts."""
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_pts"], 3)
        self.assertEqual(por_equipo["B"]["racha_pts"], 0)

    def test_victoria_visitante_cero_local_tres_visitante(self):
        """Away win → local 0 pts, visitante 3 pts."""
        partidos = [_partido("A", "B", 0, 2, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_pts"], 0)
        self.assertEqual(por_equipo["B"]["racha_pts"], 3)

    def test_empate_un_punto_a_cada_equipo(self):
        """Draw → ambos 1 pt."""
        partidos = [_partido("A", "B", 1, 1, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_pts"], 1)
        self.assertEqual(por_equipo["B"]["racha_pts"], 1)

    # ── Strings de resultado (V/E/D) ────────────────────────────────────────

    def test_victoria_local_resultado_v_local_d_visitante(self):
        partidos = [_partido("A", "B", 3, 1, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_lista"], ["V"])
        self.assertEqual(por_equipo["B"]["racha_lista"], ["D"])

    def test_victoria_visitante_resultado_d_local_v_visitante(self):
        partidos = [_partido("A", "B", 0, 1, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_lista"], ["D"])
        self.assertEqual(por_equipo["B"]["racha_lista"], ["V"])

    def test_empate_resultado_e_a_ambos(self):
        partidos = [_partido("A", "B", 0, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_lista"], ["E"])
        self.assertEqual(por_equipo["B"]["racha_lista"], ["E"])

    # ── Estructura del resultado ────────────────────────────────────────────

    def test_claves_obligatorias_presentes_sin_clasificacion(self):
        """Sin clasificacion_oficial las claves 'pos' y 'delta_pos' existen y son None."""
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        for clave in ("equipo", "racha_pts", "partidos_racha", "racha_lista", "pos_racha", "pos", "delta_pos"):
            with self.subTest(clave=clave):
                self.assertIn(clave, resultado[0])

    def test_claves_obligatorias_presentes_con_clasificacion(self):
        """Con clasificacion_oficial todas las claves deben estar presentes y no ser None."""
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]
        clasif   = [{"pos": 1, "equipo": "A"}, {"pos": 2, "equipo": "B"}]
        resultado = calcular_ranking_forma(partidos, 5, clasif)
        for clave in ("equipo", "racha_pts", "partidos_racha", "racha_lista", "pos_racha", "pos", "delta_pos"):
            with self.subTest(clave=clave):
                self.assertIn(clave, resultado[0])

    # ── Ordenación y pos_racha ───────────────────────────────────────────────

    def test_ordenado_por_racha_pts_descendente(self):
        """El equipo con más puntos de racha debe aparecer primero."""
        partidos = [
            _partido("A", "B", 3, 0, "2024-01-01"),   # A=3, B=0
            _partido("A", "B", 3, 0, "2024-01-08"),   # A=3, B=0
        ]
        resultado = calcular_ranking_forma(partidos, 5)
        pts = [r["racha_pts"] for r in resultado]
        self.assertEqual(pts, sorted(pts, reverse=True))

    def test_pos_racha_comienza_en_1(self):
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        pos_rachas = {r["equipo"]: r["pos_racha"] for r in resultado}
        # El que más puntos tiene (A=3) debe ser pos_racha=1
        self.assertEqual(pos_rachas["A"], 1)

    def test_pos_racha_es_correlativa_1_2(self):
        """Con dos equipos, pos_racha debe ser 1 y 2 (sin saltos)."""
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, 5)
        pos_rachas = sorted(r["pos_racha"] for r in resultado)
        self.assertEqual(pos_rachas, [1, 2])

    # ── Efecto de n_partidos ─────────────────────────────────────────────────

    def test_n_partidos_limita_ventana_cronologica(self):
        """
        4 partidos: primeros 2 los gana A, últimos 2 los gana B.
        Con n=2, sólo cuentan los últimos 2 → B tiene 6 pts, A tiene 0.
        Con n=4, cuentan todos → ambos 6 pts.
        """
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),   # A=3, B=0
            _partido("A", "B", 2, 0, "2024-01-08"),   # A=3, B=0
            _partido("B", "A", 2, 0, "2024-01-15"),   # B=3, A=0
            _partido("B", "A", 2, 0, "2024-01-22"),   # B=3, A=0
        ]
        resultado_n2 = calcular_ranking_forma(partidos, n_partidos=2)
        por_equipo   = {r["equipo"]: r for r in resultado_n2}
        self.assertEqual(por_equipo["A"]["racha_pts"], 0)
        self.assertEqual(por_equipo["B"]["racha_pts"], 6)

    def test_n_partidos_1_solo_cuenta_el_ultimo_partido(self):
        """n=1: sólo el partido más reciente de cada equipo contribuye."""
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),   # A gana
            _partido("B", "A", 2, 0, "2024-01-08"),   # B gana (último para ambos)
        ]
        resultado = calcular_ranking_forma(partidos, n_partidos=1)
        por_equipo = {r["equipo"]: r for r in resultado}
        # Último partido: B gana como local → B=3, A=0
        self.assertEqual(por_equipo["B"]["racha_pts"], 3)
        self.assertEqual(por_equipo["A"]["racha_pts"], 0)
        # partidos_racha debe ser 1 para ambos
        self.assertEqual(por_equipo["A"]["partidos_racha"], 1)
        self.assertEqual(por_equipo["B"]["partidos_racha"], 1)

    def test_n_partidos_mayor_que_disponibles_usa_todos(self):
        """Si n > partidos disponibles, se usan todos los partidos del equipo."""
        partidos = [_partido("A", "B", 2, 0, "2024-01-01")]   # 1 partido
        resultado = calcular_ranking_forma(partidos, n_partidos=10)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["partidos_racha"], 1)
        self.assertEqual(por_equipo["B"]["partidos_racha"], 1)

    # ── racha_lista y partidos_racha ────────────────────────────────────────

    def test_racha_lista_en_orden_cronologico(self):
        """racha_lista debe reflejar los resultados del más antiguo al más reciente."""
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),   # A gana (V) – primero
            _partido("A", "B", 0, 0, "2024-01-08"),   # empate (E)
            _partido("B", "A", 2, 0, "2024-01-15"),   # B gana, A pierde (D) – último
        ]
        resultado = calcular_ranking_forma(partidos, n_partidos=5)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["racha_lista"], ["V", "E", "D"])

    def test_partidos_racha_coincide_con_longitud_de_racha_lista(self):
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),
            _partido("A", "B", 1, 1, "2024-01-08"),
            _partido("A", "B", 0, 2, "2024-01-15"),
        ]
        resultado = calcular_ranking_forma(partidos, n_partidos=5)
        por_equipo = {r["equipo"]: r for r in resultado}
        fila_a = por_equipo["A"]
        self.assertEqual(fila_a["partidos_racha"], len(fila_a["racha_lista"]))

    def test_racha_pts_es_suma_de_puntos_de_racha_lista(self):
        """racha_pts = suma de pts de cada resultado en racha_lista."""
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),   # V = 3
            _partido("A", "B", 0, 0, "2024-01-08"),   # E = 1
            _partido("A", "B", 0, 2, "2024-01-15"),   # D = 0
        ]
        resultado = calcular_ranking_forma(partidos, n_partidos=5)
        por_equipo = {r["equipo"]: r for r in resultado}
        # V+E+D = 3+1+0 = 4
        self.assertEqual(por_equipo["A"]["racha_pts"], 4)

    # ── Sin clasificacion_oficial ────────────────────────────────────────────

    def test_sin_clasificacion_oficial_pos_none(self):
        """Sin clasificacion_oficial, 'pos' debe ser None."""
        partidos  = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, n_partidos=5)
        self.assertIsNone(resultado[0]["pos"])

    def test_sin_clasificacion_oficial_delta_pos_none(self):
        """Sin clasificacion_oficial, 'delta_pos' debe ser None."""
        partidos  = [_partido("A", "B", 2, 0, "2024-01-01")]
        resultado = calcular_ranking_forma(partidos, n_partidos=5)
        self.assertIsNone(resultado[0]["delta_pos"])

    # ── Con clasificacion_oficial ────────────────────────────────────────────

    def test_con_clasificacion_delta_pos_positivo_al_subir_en_forma(self):
        """
        A es 2.° oficial pero 1.° en forma → delta_pos = pos_oficial - pos_racha = 2-1 = +1 (sube).
        """
        partidos = [
            _partido("A", "B", 3, 0, "2024-01-01"),
            _partido("A", "B", 3, 0, "2024-01-08"),
        ]
        clasif   = [{"pos": 2, "equipo": "A"}, {"pos": 1, "equipo": "B"}]
        resultado = calcular_ranking_forma(partidos, 5, clasif)
        por_equipo = {r["equipo"]: r for r in resultado}
        # A: pos_oficial=2, pos_racha=1 → delta=1
        self.assertEqual(por_equipo["A"]["delta_pos"], 1)

    def test_con_clasificacion_delta_pos_negativo_al_bajar_en_forma(self):
        """
        B es 1.° oficial pero 2.° en forma → delta_pos = 1-2 = -1 (baja).
        """
        partidos = [
            _partido("A", "B", 3, 0, "2024-01-01"),
            _partido("A", "B", 3, 0, "2024-01-08"),
        ]
        clasif   = [{"pos": 2, "equipo": "A"}, {"pos": 1, "equipo": "B"}]
        resultado = calcular_ranking_forma(partidos, 5, clasif)
        por_equipo = {r["equipo"]: r for r in resultado}
        # B: pos_oficial=1, pos_racha=2 → delta=-1
        self.assertEqual(por_equipo["B"]["delta_pos"], -1)

    def test_con_clasificacion_delta_pos_cero_cuando_coincide(self):
        """Si pos_oficial == pos_racha, delta_pos debe ser 0."""
        partidos = [
            _partido("A", "B", 3, 0, "2024-01-01"),
            _partido("A", "B", 3, 0, "2024-01-08"),
        ]
        # A es 1.° oficial y también 1.° en forma
        clasif = [{"pos": 1, "equipo": "A"}, {"pos": 2, "equipo": "B"}]
        resultado = calcular_ranking_forma(partidos, 5, clasif)
        por_equipo = {r["equipo"]: r for r in resultado}
        self.assertEqual(por_equipo["A"]["delta_pos"], 0)

    def test_equipo_sin_match_en_clasificacion_oficial_usa_fallback_cero(self):
        """
        Equipo presente en partidos pero ausente de clasificacion_oficial:
        pos → NaN (no en la tabla oficial), delta_pos = 0 - pos_racha.
        """
        partidos = [_partido("Desconocido", "B", 2, 0, "2024-01-01")]
        clasif   = [{"pos": 1, "equipo": "B"}]
        resultado = calcular_ranking_forma(partidos, 5, clasif)
        por_equipo = {r["equipo"]: r for r in resultado}
        fila = por_equipo["Desconocido"]
        # pos debe ser NaN (no está en la clasificación oficial)
        self.assertTrue(math.isnan(fila["pos"]))
        # delta = 0 (fallback) - pos_racha → siempre ≤ 0
        self.assertEqual(fila["delta_pos"], 0 - fila["pos_racha"])

    def test_multiples_equipos_orden_correcto_por_racha_pts(self):
        """Con 3 equipos, la ordenación descendente por racha_pts debe ser correcta."""
        partidos = [
            _partido("A", "B", 2, 0, "2024-01-01"),   # A=3, B=0
            _partido("A", "C", 2, 0, "2024-01-08"),   # A=3, C=0
            _partido("B", "C", 2, 0, "2024-01-15"),   # B=3, C=0
        ]
        resultado = calcular_ranking_forma(partidos, 5)
        # A tiene 6 pts, B tiene 3 pts, C tiene 0 pts
        self.assertEqual(resultado[0]["equipo"], "A")
        self.assertEqual(resultado[0]["racha_pts"], 6)
        self.assertEqual(resultado[-1]["equipo"], "C")
        self.assertEqual(resultado[-1]["racha_pts"], 0)


# ──────────────────────────────────────────────────────────────────────────────
# 4. Tests de la vista comparador
# ──────────────────────────────────────────────────────────────────────────────

@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage"
)
class ComparadorViewTests(TestCase):
    """
    Tests HTTP de la vista comparador.

    Cubre autenticación, GET inicial y las distintas ramas del POST:
      · carga de clasificación y ranking
      · n_partidos personalizable y validación de rango
      · ranking vacío → aviso
      · RuntimeError en clasificación → error y retorno temprano
      · RuntimeError en resultados → error
      · selección de competición
    """

    def setUp(self):
        self.client = Client()
        self.user   = User.objects.create_user(username="testuser", password="testpass")
        self.url    = reverse("rachas:comparador")

    # ── Autenticación ────────────────────────────────────────────────────────

    def test_get_sin_login_redirige_a_login(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_post_sin_login_redirige(self):
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports"})
        self.assertEqual(response.status_code, 302)

    # ── GET autenticado ──────────────────────────────────────────────────────

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_renderiza_plantilla_correcta(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "rachas/comparador.html")

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_competicion_default_en_contexto(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.context["competicion_nombre"], COMPETICION_DEFAULT)

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_lista_competiciones_en_contexto(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertIsInstance(response.context["competiciones"], list)
        self.assertEqual(len(response.context["competiciones"]), len(COMPETICIONES))

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_mostrar_forma_false(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertFalse(response.context["mostrar_forma"])

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_clasificacion_en_contexto(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.context["clasificacion"], CLASIFICACION_MUESTRA)

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_ranking_none_en_contexto(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertIsNone(response.context["ranking"])

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_n_partidos_default_5(self, mock_clasif):
        mock_clasif.return_value = CLASIFICACION_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.context["n_partidos"], 5)

    # ── POST autenticado ─────────────────────────────────────────────────────

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_mostrar_forma_true_con_ranking(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["mostrar_forma"])

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_ranking_en_contexto(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "5"})
        self.assertEqual(response.context["ranking"], RANKING_MUESTRA)

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_competicion_personalizada_en_contexto(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = []
        mock_resultados.return_value = []
        mock_ranking.return_value   = []
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "Premier League", "n_partidos": "5"})
        self.assertEqual(response.context["competicion_nombre"], "Premier League")

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_n_partidos_personalizado_en_contexto(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "10"})
        self.assertEqual(response.context["n_partidos"], 10)

    # ── Validación de n_partidos ─────────────────────────────────────────────

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_n_partidos_mayor_38_clampea_a_38(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "99"})
        self.assertEqual(response.context["n_partidos"], 38)

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_n_partidos_menor_1_clampea_a_1(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "0"})
        self.assertEqual(response.context["n_partidos"], 1)

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_n_partidos_invalido_usa_default_5(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = RANKING_MUESTRA
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "abc"})
        self.assertEqual(response.context["n_partidos"], 5)

    # ── Ramas de error y advertencia ─────────────────────────────────────────

    @patch("rachas.views.calcular_ranking_forma")
    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_ranking_vacio_muestra_advertencia(self, mock_clasif, mock_resultados, mock_ranking):
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.return_value = []
        mock_ranking.return_value   = []    # sin partidos suficientes
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "5"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["mostrar_forma"])
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("partidos" in m for m in msgs))

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_error_clasificacion_muestra_mensaje_error(self, mock_clasif):
        """Si obtener_clasificacion_oficial lanza RuntimeError, debe mostrarse el error."""
        mock_clasif.side_effect = RuntimeError("límite de peticiones alcanzado")
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("límite" in m for m in msgs))

    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_get_error_clasificacion_no_renderiza_tabla(self, mock_clasif):
        """Con error en clasificación, el contexto no debe tener la tabla rellena."""
        mock_clasif.side_effect = RuntimeError("error de conexión")
        self.client.login(username="testuser", password="testpass")
        response = self.client.get(self.url)
        self.assertIsNone(response.context["clasificacion"])

    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_error_resultados_muestra_mensaje_error(self, mock_clasif, mock_resultados):
        """RuntimeError en obtener_resultados_temporada debe capturarse y mostrarse."""
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.side_effect = RuntimeError("límite de peticiones")
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "5"})
        self.assertEqual(response.status_code, 200)
        msgs = [str(m).lower() for m in response.context["messages"]]
        self.assertTrue(any("límite" in m for m in msgs))

    @patch("rachas.views.obtener_resultados_temporada")
    @patch("rachas.views.obtener_clasificacion_oficial")
    def test_post_error_resultados_no_rellena_ranking(self, mock_clasif, mock_resultados):
        """Con error en resultados, el ranking debe permanecer None (sin crash)."""
        mock_clasif.return_value    = CLASIFICACION_MUESTRA
        mock_resultados.side_effect = RuntimeError("error")
        self.client.login(username="testuser", password="testpass")
        response = self.client.post(self.url, {"competicion": "LaLiga EA Sports", "n_partidos": "5"})
        self.assertIsNone(response.context["ranking"])


# ──────────────────────────────────────────────────────────────────────────────
# 5. Tests del endpoint de autocompletado
# ──────────────────────────────────────────────────────────────────────────────

class AutocompleteCompeticionesTests(TestCase):
    """
    Tests para la vista autocomplete_competiciones (JSON, GET-only, login_required).

    Nota: a diferencia de otras apps, aquí NO hay longitud mínima de query;
    una query vacía devuelve todas las competiciones disponibles.
    """

    def setUp(self):
        self.client = Client()
        self.user   = User.objects.create_user(username="autouser", password="testpass")
        self.url    = reverse("rachas:autocomplete")

    # ── Autenticación ────────────────────────────────────────────────────────

    def test_sin_login_redirige(self):
        response = self.client.get(self.url, {"q": "LaLiga"})
        self.assertEqual(response.status_code, 302)

    def test_post_devuelve_405(self):
        """La vista está decorada con @require_GET → POST debe devolver 405."""
        self.client.login(username="autouser", password="testpass")
        response = self.client.post(self.url, {"q": "LaLiga"})
        self.assertEqual(response.status_code, 405)

    # ── Comportamiento del filtro ────────────────────────────────────────────

    def test_query_vacia_devuelve_todas_las_competiciones(self):
        """
        Query vacía ("") es substring de cualquier nombre → devuelve todas.
        COMPETICIONES tiene 6 entradas, todas dentro del límite de 8.
        """
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": ""})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["sugerencias"]), len(COMPETICIONES))

    def test_query_laliga_filtra_dos_resultados(self):
        """'laliga' → LaLiga Hypermotion y LaLiga EA Sports (2 coincidencias)."""
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "LaLiga"})
        data = response.json()
        self.assertEqual(len(data["sugerencias"]), 2)
        for nombre in data["sugerencias"]:
            self.assertIn("LaLiga", nombre)

    def test_query_sin_coincidencias_devuelve_lista_vacia(self):
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "Ekstraklasa"})
        self.assertEqual(response.json()["sugerencias"], [])

    def test_respuesta_tiene_clave_sugerencias(self):
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "Premier"})
        self.assertIn("sugerencias", response.json())

    def test_busqueda_case_insensitive(self):
        """'premier' (minúsculas) debe encontrar 'Premier League'."""
        self.client.login(username="autouser", password="testpass")
        response = self.client.get(self.url, {"q": "premier"})
        data = response.json()
        self.assertEqual(len(data["sugerencias"]), 1)
        self.assertIn("Premier League", data["sugerencias"])

    def test_resultado_maximo_8_sugerencias(self):
        """El endpoint limita la respuesta a 8 entradas."""
        self.client.login(username="autouser", password="testpass")
        # Query vacía devuelve todos; si hubiera más de 8 en COMPETICIONES, se cortaría
        response = self.client.get(self.url, {"q": ""})
        self.assertLessEqual(len(response.json()["sugerencias"]), 8)
