"""Integración Mareas IHM para Home Assistant.

Este archivo es la "puerta de entrada". Home Assistant lo usa para:

* ``async_setup``: se ejecuta UNA vez al arrancar (registramos la tarjeta
  gráfica y el servicio ``mareas_ihm.consultar_mareas``).
* ``async_setup_entry``: se ejecuta una vez POR CADA PUERTO que añadas.
* ``async_unload_entry``: cuando borras o recargas un puerto.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.typing import ConfigType
from homeassistant.loader import async_get_integration

from .api import MareasApi
from .const import DOMAIN, URL_TARJETA
from .coordinator import MareasConfigEntry, MareasCoordinator
from .services import async_registrar_servicios

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Esta integración solo se configura desde la interfaz, no desde YAML.
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Arranque global de la integración (una sola vez)."""
    await _registrar_tarjeta(hass)
    async_registrar_servicios(hass)
    return True


async def _registrar_tarjeta(hass: HomeAssistant) -> None:
    """Sirve ``frontend/mareas-card.js`` y le dice al navegador que lo cargue.

    Así el usuario no tiene que añadir el recurso a mano en los paneles.
    El ``?v=versión`` obliga al navegador a descargar la nueva versión tras
    cada actualización (si no, podría usar la copia vieja de su caché).
    """
    integracion = await async_get_integration(hass, DOMAIN)
    ruta = Path(__file__).parent / "frontend" / "mareas-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_TARJETA, str(ruta), cache_headers=True)]
    )
    add_extra_js_url(hass, f"{URL_TARJETA}?v={integracion.version}")


async def async_setup_entry(hass: HomeAssistant, entry: MareasConfigEntry) -> bool:
    """Prepara un puerto: crea el coordinador, descarga datos y crea sensores."""
    api = MareasApi(async_get_clientsession(hass))
    coordinator = MareasCoordinator(hass, entry, api)

    # Primera descarga. Si falla, HA lo reintentará solo (ConfigEntryNotReady).
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # A medianoche (hora local) cambia el día: pedimos datos nuevos.
    async def _medianoche(_now) -> None:
        await coordinator.async_request_refresh()

    entry.async_on_unload(async_track_time_change(hass, _medianoche, hour=0, minute=0, second=15))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: MareasConfigEntry) -> bool:
    """Descarga un puerto (al borrarlo, recargarlo o cambiar sus opciones)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
