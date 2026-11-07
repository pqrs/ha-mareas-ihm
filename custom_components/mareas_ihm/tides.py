"""Cálculos de mareas que no dependen de Home Assistant (fáciles de probar).

Aquí está la "lógica de negocio":

* pasar de UTC a la hora local,
* calcular la altura del agua en cualquier momento,
* decidir cuál es la próxima pleamar/bajamar,
* preparar los datos de un día o de un mes en un formato cómodo para la tarjeta.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
import math

from .api import BAJAMAR, PLEAMAR, Marea


@dataclass(frozen=True, slots=True)
class PuntoCurva:
    """Un punto de la curva de marea (altura en un instante)."""

    instante: datetime
    altura: float


# --------------------------------------------------------------------------- #
#  Zonas horarias
# --------------------------------------------------------------------------- #
def inicio_dia(dia: date, tz: tzinfo) -> datetime:
    """Medianoche local del día dado (con zona horaria)."""
    return datetime.combine(dia, time.min, tzinfo=tz)


def rango_dia(dia: date, tz: tzinfo) -> tuple[datetime, datetime]:
    """Instantes [inicio, fin) del día local, expresados en UTC.

    ¡Ojo! En Python, si dos fechas tienen la MISMA zona horaria, restarlas o
    sumarles minutos usa la "hora de reloj" e ignora el cambio de hora. Por eso
    lo pasamos todo a UTC: así un día con cambio de hora dura 23 o 25 horas.
    """
    return (
        inicio_dia(dia, tz).astimezone(UTC),
        inicio_dia(dia + timedelta(days=1), tz).astimezone(UTC),
    )


def rango_mes(anio: int, mes: int, tz: tzinfo) -> tuple[datetime, datetime]:
    """Instantes [inicio, fin) del mes local, expresados en UTC."""
    siguiente = date(anio + (mes == 12), mes % 12 + 1, 1)
    return (
        inicio_dia(date(anio, mes, 1), tz).astimezone(UTC),
        inicio_dia(siguiente, tz).astimezone(UTC),
    )


def dias_utc(inicio: datetime, fin: datetime) -> list[date]:
    """Días UTC que hay que pedir a la API para cubrir el intervalo [inicio, fin)."""
    primero = inicio.astimezone(UTC).date()
    ultimo = (fin - timedelta(microseconds=1)).astimezone(UTC).date()
    return [primero + timedelta(days=n) for n in range((ultimo - primero).days + 1)]


# --------------------------------------------------------------------------- #
#  Altura del agua
# --------------------------------------------------------------------------- #
def altura_coseno(a: Marea, b: Marea, instante: datetime) -> float:
    """Altura entre dos extremos consecutivos usando media onda de coseno.

    El agua sube/baja despacio cerca de la pleamar y la bajamar, y rápido a
    mitad de camino. Es exactamente el método que usa el propio IHM para
    dibujar su gráfico (comprobado: la diferencia es de medio milímetro).

        h(t) = (h_a + h_b)/2 + (h_a - h_b)/2 · cos(π · (t - t_a) / (t_b - t_a))
    """
    duracion = (b.instante - a.instante).total_seconds()
    if duracion <= 0:
        return a.altura
    fase = (instante - a.instante).total_seconds() / duracion
    fase = min(max(fase, 0.0), 1.0)
    return (a.altura + b.altura) / 2 + (a.altura - b.altura) / 2 * math.cos(math.pi * fase)


def altura_en(instante: datetime, mareas: Sequence[Marea]) -> float | None:
    """Altura estimada en ``instante`` (None si no hay mareas a ambos lados)."""
    anterior, siguiente = vecinas(instante, mareas)
    if anterior is None or siguiente is None:
        return None
    return altura_coseno(anterior, siguiente, instante)


def vecinas(instante: datetime, mareas: Sequence[Marea]) -> tuple[Marea | None, Marea | None]:
    """Marea inmediatamente anterior y siguiente a ``instante``."""
    anterior = siguiente = None
    for m in mareas:
        if m.instante <= instante:
            anterior = m
        else:
            siguiente = m
            break
    return anterior, siguiente


def proxima(instante: datetime, mareas: Iterable[Marea], tipo: str) -> Marea | None:
    """Primera marea del tipo indicado posterior a ``instante``."""
    return next((m for m in mareas if m.tipo == tipo and m.instante > instante), None)


def tendencia(instante: datetime, mareas: Sequence[Marea]) -> str | None:
    """'subiendo' si la próxima marea es pleamar, 'bajando' si es bajamar."""
    _, siguiente = vecinas(instante, mareas)
    if siguiente is None:
        return None
    return "subiendo" if siguiente.tipo == PLEAMAR else "bajando"


def muestrear(
    mareas: Sequence[Marea], inicio: datetime, fin: datetime, paso: timedelta
) -> list[PuntoCurva]:
    """Genera la curva para el gráfico: un punto cada ``paso``."""
    puntos: list[PuntoCurva] = []
    t = inicio
    while t <= fin:
        h = altura_en(t, mareas)
        if h is not None:
            puntos.append(PuntoCurva(t, h))
        t += paso
    return puntos


# --------------------------------------------------------------------------- #
#  Formato para Home Assistant / la tarjeta
# --------------------------------------------------------------------------- #
def marea_a_dict(m: Marea, tz: tzinfo, origen: datetime | None = None) -> dict:
    """Representación sencilla (JSON) de una marea en hora local."""
    local = m.instante.astimezone(tz)
    datos = {
        "tipo": m.tipo,
        "fecha": local.date().isoformat(),
        "hora": local.strftime("%H:%M"),
        "altura": round(m.altura, 2),
        "instante": local.isoformat(),
    }
    if origen is not None:
        # Minutos desde la medianoche local: así la tarjeta no tiene que
        # pelearse con zonas horarias para colocar el punto en el gráfico.
        datos["minuto"] = round((m.instante - origen).total_seconds() / 60)
    return datos


def resumen_texto(mareas: Iterable[Marea], tz: tzinfo) -> str:
    """Texto corto para el estado del sensor: 'Pleamar 02:56 · Bajamar 08:53 · …'."""
    partes = [
        f"{'Pleamar' if m.tipo == PLEAMAR else 'Bajamar'} {m.instante.astimezone(tz):%H:%M}"
        for m in mareas
    ]
    return " · ".join(partes) if partes else "Sin datos"


def datos_dia(dia: date, tz: tzinfo, mareas: Sequence[Marea], paso_minutos: int) -> dict:
    """Prepara todo lo necesario para mostrar un día local."""
    inicio, fin = rango_dia(dia, tz)
    del_dia = [m for m in mareas if inicio <= m.instante < fin]
    curva = muestrear(mareas, inicio, fin, timedelta(minutes=paso_minutos))
    return {
        "fecha": dia.isoformat(),
        "minutos_dia": round((fin - inicio).total_seconds() / 60),
        "mareas": [marea_a_dict(m, tz, inicio) for m in del_dia],
        "curva": [
            [round((p.instante - inicio).total_seconds() / 60), round(p.altura, 3)] for p in curva
        ],
        "resumen": resumen_texto(del_dia, tz),
    }


def datos_mes(anio: int, mes: int, tz: tzinfo, mareas: Sequence[Marea]) -> dict:
    """Prepara las mareas de un mes local agrupadas por día."""
    inicio, fin = rango_mes(anio, mes, tz)
    del_mes = [m for m in mareas if inicio <= m.instante < fin]
    dias: dict[str, dict] = {}
    for m in del_mes:
        d = marea_a_dict(m, tz)
        dia = dias.setdefault(d["fecha"], {"fecha": d["fecha"], "mareas": []})
        dia["mareas"].append({k: d[k] for k in ("tipo", "hora", "altura")})
    for dia in dias.values():
        alturas = [x["altura"] for x in dia["mareas"]]
        pleas = [x["altura"] for x in dia["mareas"] if x["tipo"] == PLEAMAR]
        bajas = [x["altura"] for x in dia["mareas"] if x["tipo"] == BAJAMAR]
        # Carrera de marea: diferencia entre la pleamar y la bajamar del día.
        # Si es grande hay "mareas vivas"; si es pequeña, "mareas muertas".
        dia["carrera"] = round(max(pleas) - min(bajas), 2) if pleas and bajas else None
        dia["max"] = max(alturas)
        dia["min"] = min(alturas)
    return {
        "anio": anio,
        "mes": mes,
        "dias": list(dias.values()),
        "total_mareas": len(del_mes),
    }
