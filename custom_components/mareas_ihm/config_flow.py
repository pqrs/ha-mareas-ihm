"""Asistente de configuración (las ventanas que ves al añadir la integración)."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)
import voluptuous as vol

from .api import MareasApi, MareasConexionError, MareasError, Puerto
from .const import (
    CONF_MOSTRAR_MES,
    CONF_PASO_CURVA,
    CONF_PUERTO_CODE,
    CONF_PUERTO_ID,
    CONF_PUERTO_NOMBRE,
    DOMAIN,
    PASO_CURVA_DEFECTO,
    PASOS_CURVA,
)
from .coordinator import MareasConfigEntry

_LOGGER = logging.getLogger(__name__)


class MareasConfigFlow(ConfigFlow, domain=DOMAIN):
    """Paso 1 (y único): elegir el puerto de una lista desplegable."""

    VERSION = 1

    def __init__(self) -> None:
        self._puertos: dict[str, Puerto] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errores: dict[str, str] = {}

        # 1) El usuario ya eligió puerto -> creamos la entrada.
        if user_input is not None and user_input[CONF_PUERTO_ID] in self._puertos:
            puerto = self._puertos[user_input[CONF_PUERTO_ID]]
            # El id del puerto es único: no se puede añadir dos veces el mismo.
            await self.async_set_unique_id(puerto.id)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=puerto.nombre,
                data={
                    CONF_PUERTO_ID: puerto.id,
                    CONF_PUERTO_CODE: puerto.code,
                    CONF_PUERTO_NOMBRE: puerto.nombre,
                },
            )

        # 2) Primera vez: descargamos la lista de puertos para el desplegable.
        if not self._puertos:
            try:
                api = MareasApi(async_get_clientsession(self.hass))
                self._puertos = {p.id: p for p in await api.puertos()}
            except MareasConexionError:
                errores["base"] = "cannot_connect"
            except MareasError:
                _LOGGER.exception("Respuesta inesperada al pedir los puertos")
                errores["base"] = "unknown"

        if errores:
            return self.async_show_form(step_id="user", errors=errores)

        opciones = [SelectOptionDict(value=p.id, label=p.nombre) for p in self._puertos.values()]
        esquema = vol.Schema(
            {
                vol.Required(CONF_PUERTO_ID): SelectSelector(
                    SelectSelectorConfig(options=opciones, mode=SelectSelectorMode.DROPDOWN)
                )
            }
        )
        return self.async_show_form(step_id="user", data_schema=esquema)

    @staticmethod
    @callback
    def async_get_options_flow(entry: MareasConfigEntry) -> MareasOptionsFlow:
        return MareasOptionsFlow()


class MareasOptionsFlow(OptionsFlowWithReload):
    """Botón "Configurar" de la integración. Al guardar, se recarga sola."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        actuales = self.config_entry.options
        esquema = vol.Schema(
            {
                vol.Required(
                    CONF_PASO_CURVA,
                    default=str(actuales.get(CONF_PASO_CURVA, PASO_CURVA_DEFECTO)),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=PASOS_CURVA,
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key=CONF_PASO_CURVA,
                    )
                ),
                vol.Required(
                    CONF_MOSTRAR_MES, default=actuales.get(CONF_MOSTRAR_MES, True)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=esquema)
