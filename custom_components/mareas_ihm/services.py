"""Servicio (acción) ``mareas_ihm.consultar_mareas``.

Permite pedir las mareas de CUALQUIER día o mes del año en curso y recibir la
respuesta. Lo usa la tarjeta para navegar (◀ ▶) y lo puedes usar en
automatizaciones o scripts con ``response_variable``.
"""

from __future__ import annotations

from datetime import date

from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import MareasApi, MareasError, MareasSinDatos
from .const import DOMAIN, PASO_CURVA_DEFECTO, SERVICIO_CONSULTAR
from .coordinator import consultar_dia, consultar_mes

ESQUEMA = vol.Schema(
    {
        vol.Required("puerto_id"): cv.string,
        # "fecha" y "mes" son excluyentes: o pides un día o pides un mes.
        vol.Exclusive("fecha", "periodo"): cv.date,
        vol.Exclusive("mes", "periodo"): cv.matches_regex(r"^\d{4}-(0[1-9]|1[0-2])$"),
        vol.Optional("paso_curva", default=PASO_CURVA_DEFECTO): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=60)
        ),
    }
)


@callback
def async_registrar_servicios(hass: HomeAssistant) -> None:
    """Registra el servicio (se llama una vez desde ``async_setup``)."""

    async def _consultar(call: ServiceCall) -> ServiceResponse:
        api = MareasApi(async_get_clientsession(hass))
        tz = dt_util.get_default_time_zone()
        puerto = call.data["puerto_id"]
        try:
            if "mes" in call.data:
                anio, mes = (int(x) for x in call.data["mes"].split("-"))
                return {"puerto_id": puerto, **await consultar_mes(api, puerto, anio, mes, tz)}
            dia: date = call.data.get("fecha") or dt_util.now().date()
            datos, _ = await consultar_dia(api, puerto, dia, tz, call.data["paso_curva"])
            return {"puerto_id": puerto, **datos}
        except MareasSinDatos as err:
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="sin_datos"
            ) from err
        except MareasError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="error_api",
                translation_placeholders={"error": str(err)},
            ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICIO_CONSULTAR,
        _consultar,
        schema=ESQUEMA,
        supports_response=SupportsResponse.ONLY,
    )
