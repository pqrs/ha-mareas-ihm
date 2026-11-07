"""Cliente para la API de mareas del Instituto Hidrográfico de la Marina (IHM).

Este módulo NO depende de Home Assistant: solo de ``aiohttp``. Así se puede
probar por separado y reutilizar en cualquier otro programa.

Documentación de la API (se obtiene llamando a un "request" no válido):
    https://ideihm.covam.es/api-ihm/getmarea?request=help

Puntos importantes descubiertos al estudiar la API:

* ``request=getlist&format=json``  -> lista de puertos.
* ``request=gettide&id=ID&date=YYYYMMDD&format=json`` -> pleamares/bajamares de un día.
* ``request=gettide&id=ID&month=YYYYMM&format=json``  -> pleamares/bajamares de un mes.
* ``format=gra`` devuelve una página HTML con un gráfico. No lo usamos: hemos
  comprobado que su curva es una interpolación coseno entre pleamares y
  bajamares, así que la calculamos nosotros (ver ``tides.py``).
* TODAS las horas están en UTC (el propio gráfico dice "Horas UTC").
* Solo hay datos del año en curso; para otras fechas responde con el texto
  "No existen datos para esa fecha".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
import json

import aiohttp

BASE_URL = "https://ideihm.covam.es/api-ihm/getmarea"
TIMEOUT = aiohttp.ClientTimeout(total=30)

PLEAMAR = "pleamar"
BAJAMAR = "bajamar"


class MareasError(Exception):
    """Error genérico al hablar con la API."""


class MareasConexionError(MareasError):
    """No se ha podido contactar con el servidor."""


class MareasSinDatos(MareasError):
    """La API responde, pero no tiene datos para lo que pedimos."""


@dataclass(frozen=True, slots=True)
class Puerto:
    """Un puerto con predicción de marea."""

    id: str
    code: str
    nombre: str
    lat: float
    lon: float


@dataclass(frozen=True, slots=True)
class Marea:
    """Una pleamar o bajamar. ``instante`` siempre en UTC (con zona horaria)."""

    instante: datetime
    altura: float
    tipo: str  # "pleamar" o "bajamar"


def _utc(fecha: str, hora: str) -> datetime:
    """Convierte '2026-11-07' + '01:57' (UTC) en un datetime con zona UTC."""
    return datetime.strptime(f"{fecha} {hora}", "%Y-%m-%d %H:%M").replace(tzinfo=UTC)


def parse_puertos(payload: dict) -> list[Puerto]:
    """Convierte la respuesta JSON de ``getlist`` en una lista de Puerto."""
    try:
        crudos = payload["estaciones"]["puertos"]
    except (KeyError, TypeError) as err:
        raise MareasError("Respuesta de lista de puertos inesperada") from err
    puertos = [
        Puerto(
            id=str(p["id"]),
            code=str(p.get("code", "")),
            nombre=str(p["puerto"]),
            lat=float(p.get("lat", 0)),
            lon=float(p.get("lon", 0)),
        )
        for p in crudos
    ]
    return sorted(puertos, key=lambda p: p.nombre.lower())


def parse_mareas(payload: dict) -> list[Marea]:
    """Convierte la respuesta JSON de ``gettide`` (día o mes) en una lista de Marea.

    En la respuesta diaria la fecha va en la cabecera (``mareas.fecha``); en la
    mensual cada marea trae su propia ``fecha``. Tratamos ambos casos igual.
    """
    try:
        cabecera = payload["mareas"]
        crudas = cabecera["datos"]["marea"]
    except (KeyError, TypeError) as err:
        raise MareasError("Respuesta de mareas inesperada") from err
    if isinstance(crudas, dict):  # por si algún día devuelve un único elemento
        crudas = [crudas]
    fecha_cabecera = cabecera.get("fecha")
    mareas = []
    for m in crudas:
        fecha = m.get("fecha", fecha_cabecera)
        tipo = str(m["tipo"]).lower()
        if tipo not in (PLEAMAR, BAJAMAR):
            continue
        mareas.append(Marea(_utc(fecha, m["hora"]), float(m["altura"]), tipo))
    return sorted(mareas, key=lambda m: m.instante)


class MareasApi:
    """Cliente asíncrono. Recibe una sesión aiohttp (Home Assistant nos da una)."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def _get(self, **params: str) -> str:
        """Hace una petición GET y devuelve el texto de la respuesta."""
        try:
            async with self._session.get(BASE_URL, params=params, timeout=TIMEOUT) as resp:
                resp.raise_for_status()
                crudo = await resp.read()
        except (TimeoutError, aiohttp.ClientError) as err:
            raise MareasConexionError(f"Error de conexión con el IHM: {err}") from err
        # El JSON llega en UTF-8, pero los mensajes de error en Latin-1.
        try:
            return crudo.decode("utf-8")
        except UnicodeDecodeError:
            return crudo.decode("latin-1")

    async def _get_json(self, **params: str) -> dict:
        texto = await self._get(format="json", **params)
        if texto.lstrip().startswith("No existen datos"):
            raise MareasSinDatos(texto.splitlines()[0].strip())
        try:
            return json.loads(texto)
        except ValueError as err:
            primera = texto.strip().splitlines()[0] if texto.strip() else "vacía"
            raise MareasError(f"Respuesta no válida de la API: {primera}") from err

    async def puertos(self) -> list[Puerto]:
        """Lista de todos los puertos disponibles."""
        return parse_puertos(await self._get_json(request="getlist"))

    async def mareas_dia(self, puerto_id: str, dia: date) -> list[Marea]:
        """Pleamares y bajamares de un día (día UTC)."""
        payload = await self._get_json(request="gettide", id=puerto_id, date=dia.strftime("%Y%m%d"))
        return parse_mareas(payload)

    async def mareas_mes(self, puerto_id: str, anio: int, mes: int) -> list[Marea]:
        """Pleamares y bajamares de un mes completo (mes UTC)."""
        payload = await self._get_json(
            request="gettide", id=puerto_id, month=f"{anio:04d}{mes:02d}"
        )
        return parse_mareas(payload)
