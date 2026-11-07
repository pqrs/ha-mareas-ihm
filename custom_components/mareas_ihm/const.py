"""Constantes compartidas por toda la integración."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "mareas_ihm"
ATTRIBUTION: Final = "Datos: © Instituto Hidrográfico de la Marina (IHM)"

# Claves guardadas en la entrada de configuración (config entry)
CONF_PUERTO_ID: Final = "puerto_id"
CONF_PUERTO_CODE: Final = "puerto_code"
CONF_PUERTO_NOMBRE: Final = "puerto_nombre"

# Opciones que el usuario puede cambiar después
CONF_PASO_CURVA: Final = "paso_curva"
CONF_MOSTRAR_MES: Final = "mostrar_mes"
PASO_CURVA_DEFECTO: Final = 10  # minutos entre puntos del gráfico diario
PASOS_CURVA: Final = ["5", "10", "15", "30", "60"]

# Cada cuánto se vuelve a preguntar a la API (las predicciones no cambian)
INTERVALO_ACTUALIZACION: Final = timedelta(hours=6)
# Cada cuánto se recalcula la altura actual y las próximas mareas (sin red)
INTERVALO_RECALCULO: Final = timedelta(minutes=5)

# Tarjeta de Lovelace que va dentro de la integración
URL_TARJETA: Final = f"/{DOMAIN}/mareas-card.js"

SERVICIO_CONSULTAR: Final = "consultar_mareas"
