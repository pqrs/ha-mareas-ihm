"""Sensores de mareas.

Por cada puerto se crean estos sensores:

=================  ===================================================
mareas_hoy         Texto "Pleamar 02:56 · Bajamar 08:53 · …" + curva del día
mareas_mes         Mes actual con todas sus pleamares/bajamares por día
altura_actual      Altura estimada del agua ahora mismo (m)
tendencia          "subiendo" o "bajando"
proxima_pleamar    Fecha/hora de la próxima pleamar
proxima_bajamar    Fecha/hora de la próxima bajamar
=================  ===================================================
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import UnitOfLength
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .api import BAJAMAR, PLEAMAR
from .const import ATTRIBUTION, CONF_PUERTO_CODE, CONF_PUERTO_NOMBRE, DOMAIN, INTERVALO_RECALCULO
from .coordinator import DatosMareas, MareasConfigEntry, MareasCoordinator
from .tides import altura_en, proxima, tendencia

# Las actualizaciones las hace el coordinador: no limitamos el paralelismo.
PARALLEL_UPDATES = 0

MESES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
    "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]  # fmt: skip


@dataclass(frozen=True, kw_only=True)
class MareasSensorDescription(SensorEntityDescription):
    """Describe un sensor: cómo calcular su valor y sus atributos."""

    value_fn: Callable[[DatosMareas, datetime], Any]
    attrs_fn: Callable[[DatosMareas, datetime], dict[str, Any]] | None = None
    en_vivo: bool = False  # True -> se recalcula cada 5 minutos sin ir a la API
    requiere_mes: bool = False


def _proxima_attrs(tipo: str) -> Callable[[DatosMareas, datetime], dict[str, Any]]:
    def _attrs(datos: DatosMareas, ahora: datetime) -> dict[str, Any]:
        m = proxima(ahora, datos.mareas, tipo)
        return {"altura": round(m.altura, 2)} if m else {}

    return _attrs


def _altura(datos: DatosMareas, ahora: datetime) -> float | None:
    h = altura_en(ahora, datos.mareas)
    return round(h, 2) if h is not None else None


def _txt(m: dict) -> str:
    return f"{m['hora']} ({m['altura']} m)"


def _mareas_hoy_attrs(datos: DatosMareas, ahora: datetime) -> dict[str, Any]:
    dia = datos.dia
    return {
        "fecha": dia["fecha"],
        "pleamares": [_txt(m) for m in dia["mareas"] if m["tipo"] == PLEAMAR],
        "bajamares": [_txt(m) for m in dia["mareas"] if m["tipo"] == BAJAMAR],
        "mareas": dia["mareas"],
        "curva": dia["curva"],
        "minutos_dia": dia["minutos_dia"],
    }


def _mes_valor(datos: DatosMareas, ahora: datetime) -> str | None:
    if not datos.mes:
        return None
    return f"{MESES[datos.mes['mes'] - 1].capitalize()} {datos.mes['anio']}"


def _mes_attrs(datos: DatosMareas, ahora: datetime) -> dict[str, Any]:
    return dict(datos.mes) if datos.mes else {}


SENSORES: tuple[MareasSensorDescription, ...] = (
    MareasSensorDescription(
        key="mareas_hoy",
        translation_key="mareas_hoy",
        value_fn=lambda d, _: d.dia["resumen"],
        attrs_fn=_mareas_hoy_attrs,
    ),
    MareasSensorDescription(
        key="mareas_mes",
        translation_key="mareas_mes",
        value_fn=_mes_valor,
        attrs_fn=_mes_attrs,
        requiere_mes=True,
    ),
    MareasSensorDescription(
        key="altura_actual",
        translation_key="altura_actual",
        device_class=SensorDeviceClass.DISTANCE,
        native_unit_of_measurement=UnitOfLength.METERS,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=2,
        value_fn=_altura,
        en_vivo=True,
    ),
    MareasSensorDescription(
        key="tendencia",
        translation_key="tendencia",
        device_class=SensorDeviceClass.ENUM,
        options=["subiendo", "bajando"],
        value_fn=lambda d, ahora: tendencia(ahora, d.mareas),
        en_vivo=True,
    ),
    MareasSensorDescription(
        key="proxima_pleamar",
        translation_key="proxima_pleamar",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, ahora: getattr(proxima(ahora, d.mareas, PLEAMAR), "instante", None),
        attrs_fn=_proxima_attrs(PLEAMAR),
        en_vivo=True,
    ),
    MareasSensorDescription(
        key="proxima_bajamar",
        translation_key="proxima_bajamar",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, ahora: getattr(proxima(ahora, d.mareas, BAJAMAR), "instante", None),
        attrs_fn=_proxima_attrs(BAJAMAR),
        en_vivo=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: MareasConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Crea los sensores de un puerto."""
    coordinator = entry.runtime_data
    if not coordinator.mostrar_mes:
        # Si el usuario desactiva el sensor del mes, lo borramos del registro
        # para que no se quede como "no disponible".
        registro = er.async_get(hass)
        if entity_id := registro.async_get_entity_id(
            "sensor", DOMAIN, f"{entry.unique_id}_mareas_mes"
        ):
            registro.async_remove(entity_id)
    async_add_entities(
        MareasSensor(coordinator, desc)
        for desc in SENSORES
        if not desc.requiere_mes or coordinator.mostrar_mes
    )


class MareasSensor(CoordinatorEntity[MareasCoordinator], SensorEntity):
    """Un sensor genérico: su comportamiento lo define la descripción."""

    entity_description: MareasSensorDescription
    _attr_has_entity_name = True  # nombre final = "<puerto> <nombre del sensor>"
    _attr_attribution = ATTRIBUTION
    # Atributos grandes que NO se guardan en el historial (base de datos).
    _unrecorded_attributes = frozenset({"mareas", "curva", "dias", "minutos_dia"})

    def __init__(self, coordinator: MareasCoordinator, desc: MareasSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = desc
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.unique_id}_{desc.key}"
        # Todos los sensores de un puerto se agrupan en un "dispositivo".
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.data[CONF_PUERTO_NOMBRE],
            manufacturer="Instituto Hidrográfico de la Marina",
            model=f"Puerto {entry.data[CONF_PUERTO_CODE]}",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://ideihm.covam.es/portal/api-mareas/",
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.en_vivo:
            # Cada 5 minutos recalculamos (sin red) la altura y las próximas mareas.
            self.async_on_remove(
                async_track_time_interval(self.hass, self._recalcular, INTERVALO_RECALCULO)
            )

    @callback
    def _recalcular(self, _now: datetime) -> None:
        self.async_write_ha_state()

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data, dt_util.utcnow())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        datos = self.coordinator.data
        attrs: dict[str, Any] = {"puerto_id": self.coordinator.puerto_id}
        if self.entity_description.attrs_fn:
            attrs.update(self.entity_description.attrs_fn(datos, dt_util.utcnow()))
        return attrs
