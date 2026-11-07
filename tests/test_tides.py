"""Pruebas de la lógica de mareas usando respuestas reales guardadas de la API.

Ejecutar con:  python -m pytest tests -v
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import pytest

from custom_components.mareas_ihm.api import (
    BAJAMAR,
    PLEAMAR,
    Marea,
    parse_mareas,
    parse_puertos,
)
from custom_components.mareas_ihm.tides import (
    altura_coseno,
    altura_en,
    datos_dia,
    datos_mes,
    dias_utc,
    proxima,
    rango_dia,
    resumen_texto,
    tendencia,
)

FIX = Path(__file__).parent / "fixtures"

# El gráfico HTML del IHM (format=gra) trae la curva en "var data = [...]".
# La integración no lo usa; aquí lo leemos solo para comparar con nuestra curva.
_DATA_RE = re.compile(r"var\s+data\s*=\s*\[(.*?)\]", re.S)
_PUNTO_RE = re.compile(r"\{x\s*:\s*'([\d\- :]+)'\s*,\s*y\s*:\s*(-?[\d.]+)\s*\}")


def curva_ihm(html: str) -> list[tuple[datetime, float]]:
    bloque = _DATA_RE.search(html).group(1)
    return [
        (datetime.strptime(x, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC), float(y))
        for x, y in _PUNTO_RE.findall(bloque)
    ]


MADRID = ZoneInfo("Europe/Madrid")
CANARIAS = ZoneInfo("Atlantic/Canary")


def cargar(nombre: str) -> dict:
    return json.loads((FIX / nombre).read_text(encoding="utf-8"))


def test_lista_de_puertos():
    puertos = parse_puertos(cargar("puertos.json"))
    assert len(puertos) >= 60
    cadiz = next(p for p in puertos if p.id == "42")
    assert cadiz.nombre == "Cádiz"
    assert cadiz.code == "cadiz"
    # Ordenados alfabéticamente para el desplegable
    assert [p.nombre.lower() for p in puertos] == sorted(p.nombre.lower() for p in puertos)


def test_mareas_dia_en_utc():
    mareas = parse_mareas(cargar("dia_cadiz_20261107.json"))
    assert [m.tipo for m in mareas] == [PLEAMAR, BAJAMAR, PLEAMAR, BAJAMAR]
    assert mareas[0].instante == datetime(2026, 11, 7, 0, 36, tzinfo=UTC)
    assert mareas[0].altura == pytest.approx(3.184)
    # En noviembre Madrid es UTC+1
    assert mareas[0].instante.astimezone(MADRID).strftime("%H:%M") == "01:36"


def test_mareas_mes():
    mareas = parse_mareas(cargar("mes_cadiz_202611.json"))
    assert len(mareas) > 100
    assert all(m.instante.month == 11 for m in mareas)
    assert mareas == sorted(mareas, key=lambda m: m.instante)


def test_grafico_ihm_en_utc():
    curva = curva_ihm((FIX / "curva_cadiz_20261107.html").read_text(encoding="utf-8"))
    # Cada 5 minutos de 00:00 a 24:00 UTC (289 puntos)
    assert len(curva) == 289
    assert curva[0][0] == datetime(2026, 11, 7, 0, 0, tzinfo=UTC)
    assert curva[1][0] - curva[0][0] == timedelta(minutes=5)


def test_dias_utc_para_un_dia_local():
    inicio, fin = rango_dia(date(2026, 11, 7), MADRID)
    # El 7/11 local empieza el 6/11 a las 23:00 UTC
    assert dias_utc(inicio, fin) == [date(2026, 11, 6), date(2026, 11, 7)]
    inicio, fin = rango_dia(date(2026, 11, 7), CANARIAS)  # UTC+0 en invierno
    assert dias_utc(inicio, fin) == [date(2026, 11, 7)]


def test_dia_con_cambio_de_hora():
    inicio, fin = rango_dia(date(2026, 10, 25), MADRID)  # se atrasa la hora
    assert (fin - inicio) == timedelta(hours=25)
    inicio, fin = rango_dia(date(2026, 3, 29), MADRID)  # se adelanta la hora
    assert (fin - inicio) == timedelta(hours=23)
    mareas = parse_mareas(cargar("mes_cadiz_202611.json"))
    d = datos_dia(date(2026, 10, 25), MADRID, mareas, 60)
    assert d["minutos_dia"] == 1500


def test_coseno_extremos_y_mitad():
    a = Marea(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), 3.0, PLEAMAR)
    b = Marea(datetime(2026, 1, 1, 6, 0, tzinfo=UTC), 1.0, BAJAMAR)
    assert altura_coseno(a, b, a.instante) == pytest.approx(3.0)
    assert altura_coseno(a, b, b.instante) == pytest.approx(1.0)
    assert altura_coseno(a, b, a.instante + timedelta(hours=3)) == pytest.approx(2.0)


def test_nuestra_curva_es_la_del_ihm():
    """Nuestro coseno coincide con la curva del gráfico oficial (< 1 mm)."""
    curva = curva_ihm((FIX / "curva_cadiz_20261107.html").read_text(encoding="utf-8"))
    mareas = parse_mareas(cargar("mes_cadiz_202611.json"))
    errores = [abs(altura_en(t, mareas) - h) for t, h in curva]
    assert max(errores) < 0.001


def test_proxima_y_tendencia():
    mareas = parse_mareas(cargar("dia_cadiz_20261107.json"))
    ahora = datetime(2026, 11, 7, 3, 0, tzinfo=UTC)  # entre pleamar 00:36 y bajamar 06:37
    assert proxima(ahora, mareas, BAJAMAR).instante.hour == 6
    assert proxima(ahora, mareas, PLEAMAR).instante.hour == 12
    assert tendencia(ahora, mareas) == "bajando"


def test_datos_dia():
    mareas = parse_mareas(cargar("mes_cadiz_202611.json"))
    d = datos_dia(date(2026, 11, 7), MADRID, mareas, 10)
    assert d["fecha"] == "2026-11-07"
    assert d["minutos_dia"] == 1440
    assert d["mareas"][0]["hora"] == "01:36"
    assert d["mareas"][0]["minuto"] == 96
    assert d["resumen"].startswith("Pleamar 01:36 · Bajamar 07:37")
    # La curva cubre el día completo, de 00:00 a 24:00, un punto cada 10 min
    assert d["curva"][0][0] == 0
    assert d["curva"][-1][0] == 1440
    assert len(d["curva"]) == 145


def test_datos_mes():
    mareas = parse_mareas(cargar("mes_cadiz_202611.json"))
    m = datos_mes(2026, 11, MADRID, mareas)
    assert m["dias"][0]["fecha"] == "2026-11-01"
    assert all(d["carrera"] is None or d["carrera"] > 0 for d in m["dias"])
    # La última marea UTC del 30/11 a las 23:xx sería ya 1/12 local -> fuera
    assert all(d["fecha"].startswith("2026-11") for d in m["dias"])


def test_resumen_vacio():
    assert resumen_texto([], MADRID) == "Sin datos"
