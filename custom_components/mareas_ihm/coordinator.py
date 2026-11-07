"""Coordinador: pide los datos a la API y los reparte entre todos los sensores.

En Home Assistant, si cinco sensores necesitan los mismos datos, no se hacen
cinco peticiones: un ``DataUpdateCoordinator`` las hace una vez y avisa a todos.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import Marea, MareasApi, MareasError, MareasSinDatos
from .const import (
    CONF_MOSTRAR_MES,
    CONF_PASO_CURVA,
    CONF_PUERTO_ID,
    CONF_PUERTO_NOMBRE,
    DOMAIN,
    INTERVALO_ACTUALIZACION,
    PASO_CURVA_DEFECTO,
)
from .tides import datos_dia, datos_mes, dias_utc, rango_dia, rango_mes

_LOGGER = logging.getLogger(__name__)

# "Alias de tipo": una entrada de configuración cuyo runtime_data es el coordinador.
type MareasConfigEntry = ConfigEntry[MareasCoordinator]


@dataclass
class DatosMareas:
    """Todo lo que el coordinador sabe en un momento dado."""

    hoy: date
    mareas: list[Marea]  # de ayer a mañana, para calcular "próxima" y "actual"
    dia: dict  # datos ya preparados del día de hoy
    mes: dict | None = None  # datos del mes (si la opción está activada)
    actualizado: datetime = field(default_factory=dt_util.utcnow)


# --------------------------------------------------------------------------- #
#  Funciones de consulta reutilizables (las usan el coordinador y el servicio)
# --------------------------------------------------------------------------- #
async def _mareas_de_dias(
    api: MareasApi, puerto_id: str, dias: list[date], obligatorios: set[date]
) -> list[Marea]:
    """Pide varios días UTC a la vez. Los días "de margen" pueden fallar sin más."""
    resultados = await asyncio.gather(
        *(api.mareas_dia(puerto_id, d) for d in dias), return_exceptions=True
    )
    mareas: list[Marea] = []
    for dia, res in zip(dias, resultados, strict=True):
        if isinstance(res, BaseException):
            if dia in obligatorios or not isinstance(res, MareasSinDatos):
                raise res
            continue  # p. ej. 31/12 -> 1/1: la API solo tiene el año en curso
        mareas.extend(res)
    return _sin_duplicados(mareas)


def _sin_duplicados(mareas: list[Marea]) -> list[Marea]:
    unicas = {(m.instante, m.tipo): m for m in mareas}
    return sorted(unicas.values(), key=lambda m: m.instante)


async def consultar_dia(
    api: MareasApi, puerto_id: str, dia: date, tz: tzinfo, paso: int
) -> tuple[dict, list[Marea]]:
    """Datos de un día local cualquiera.

    Pedimos también el día anterior y el siguiente: hacen falta para dibujar
    la curva de madrugada y por la noche, y para saber la "próxima" marea.
    """
    inicio, fin = rango_dia(dia, tz)
    nucleo = set(dias_utc(inicio, fin))
    margen = dias_utc(inicio - timedelta(days=1), fin + timedelta(days=1))
    mareas = await _mareas_de_dias(api, puerto_id, margen, nucleo)
    return datos_dia(dia, tz, mareas, paso), mareas


async def consultar_mes(api: MareasApi, puerto_id: str, anio: int, mes: int, tz: tzinfo) -> dict:
    """Datos de un mes local cualquiera.

    El mes local empieza 1-2 horas antes que el mes UTC (en España peninsular),
    así que además del mes pedimos el último día UTC del mes anterior.
    """
    inicio, fin = rango_mes(anio, mes, tz)
    extra = [d for d in dias_utc(inicio, fin) if (d.year, d.month) != (anio, mes)]
    principal, adicionales = await asyncio.gather(
        api.mareas_mes(puerto_id, anio, mes),
        _mareas_de_dias(api, puerto_id, extra, set()),
    )
    return datos_mes(anio, mes, tz, _sin_duplicados(principal + adicionales))


# --------------------------------------------------------------------------- #
#  El coordinador
# --------------------------------------------------------------------------- #
class MareasCoordinator(DataUpdateCoordinator[DatosMareas]):
    """Mantiene actualizadas las mareas de un puerto."""

    config_entry: MareasConfigEntry

    def __init__(self, hass: HomeAssistant, entry: MareasConfigEntry, api: MareasApi) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.data[CONF_PUERTO_NOMBRE]}",
            update_interval=INTERVALO_ACTUALIZACION,
        )
        self.api = api
        self.puerto_id: str = entry.data[CONF_PUERTO_ID]
        self._cache_mes: tuple[tuple[int, int, date], dict] | None = None

    @property
    def paso_curva(self) -> int:
        return int(self.config_entry.options.get(CONF_PASO_CURVA, PASO_CURVA_DEFECTO))

    @property
    def mostrar_mes(self) -> bool:
        return bool(self.config_entry.options.get(CONF_MOSTRAR_MES, True))

    async def _async_update_data(self) -> DatosMareas:
        """Home Assistant llama a esto cada INTERVALO_ACTUALIZACION."""
        tz = dt_util.get_default_time_zone()
        hoy = dt_util.now().date()
        try:
            dia, mareas = await consultar_dia(self.api, self.puerto_id, hoy, tz, self.paso_curva)
            mes = await self._mes(hoy, tz) if self.mostrar_mes else None
        except MareasError as err:
            # UpdateFailed hace que las entidades se muestren "no disponibles"
            # y que HA lo reintente más tarde.
            raise UpdateFailed(str(err)) from err
        return DatosMareas(hoy=hoy, mareas=mareas, dia=dia, mes=mes)

    async def _mes(self, hoy: date, tz: tzinfo) -> dict:
        """El mes solo se descarga una vez al día (no cambia)."""
        clave = (hoy.year, hoy.month, hoy)
        if self._cache_mes and self._cache_mes[0] == clave:
            return self._cache_mes[1]
        datos = await consultar_mes(self.api, self.puerto_id, hoy.year, hoy.month, tz)
        self._cache_mes = (clave, datos)
        return datos
