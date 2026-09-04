"""Cliente de la API externa de farmacos.

Unica capa del proyecto autorizada a hablar por HTTP con el servicio externo.
Ni views, ni serializers, ni modelos realizan peticiones: siempre pasan por
aqui (`Service -> Client -> External API`).

Diseno pensado para crecer sin tocar la view:

  * `FarmacosService.list_farmacos()` es el unico punto de entrada publico. Una
    futura capa de cache Redis, una tarea Celery de sincronizacion o una
    persistencia en PostgreSQL se insertan dentro de este metodo.
  * `FarmacosAPIClient` solo sabe de transporte: construir la peticion,
    ejecutarla y traducir fallos a errores de dominio.

No se implementa cache en esta version (`FARMACOS_CACHE_TTL` existe en settings
pero todavia no se usa), ni Celery, ni persistencia.
"""

from __future__ import annotations

import logging
from typing import Any, Final

import httpx
import sentry_sdk
from django.conf import settings
from rest_framework import serializers

from apps.medications.exceptions import (
    FarmacosAPIBadRequestError,
    FarmacosAPIConnectionError,
    FarmacosAPIError,
    FarmacosAPIResponseError,
    FarmacosAPITimeoutError,
)
from apps.medications.serializers import FarmacoSerializer

logger = logging.getLogger(__name__)

# Ruta del recurso dentro de la API externa. Es parte del contrato publicado
# del servicio, no configuracion de despliegue: el host (lo unico que cambia
# entre entornos) viene de FARMACOS_API_BASE_URL.
FARMACOS_ENDPOINT_PATH: Final[str] = "/v1/farmacos"

# Limites del pool. Reutilizar conexiones es lo que mantiene la latencia baja
# cuando llegan consultas repetidas de autocompletado.
_POOL_LIMITS: Final[httpx.Limits] = httpx.Limits(
    max_connections=10, max_keepalive_connections=5
)

_client: httpx.Client | None = None
_client_config: tuple[str, float, str] | None = None


def _current_config() -> tuple[str, float, str]:
    """Configuracion vigente del cliente, leida siempre de settings."""
    return (
        str(settings.FARMACOS_API_BASE_URL).rstrip("/"),
        float(settings.FARMACOS_API_TIMEOUT),
        str(getattr(settings, "FARMACOS_API_KEY", "") or ""),
    )


def _build_client(base_url: str, timeout: float, api_key: str) -> httpx.Client:
    headers = {"Accept": "application/json"}
    # La API es hoy publica y sin autenticacion. Si en el futuro exige una
    # credencial, basta con definir FARMACOS_API_KEY: no hay que tocar codigo.
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return httpx.Client(
        base_url=base_url,
        timeout=timeout,
        limits=_POOL_LIMITS,
        headers=headers,
        follow_redirects=False,
    )


def get_client() -> httpx.Client:
    """Devuelve el cliente compartido, reconstruyendolo si cambio la config.

    Comparar contra la configuracion vigente permite que `override_settings`
    funcione en los tests sin necesidad de reiniciar nada a mano.
    """
    global _client, _client_config

    config = _current_config()
    if _client is None or _client_config != config:
        reset_client()
        _client = _build_client(*config)
        _client_config = config
    return _client


def reset_client() -> None:
    """Cierra y descarta el cliente compartido."""
    global _client, _client_config

    if _client is not None:
        _client.close()
    _client = None
    _client_config = None


class FarmacosAPIClient:
    """Transporte HTTP contra la API externa de farmacos."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        # Inyectable para tests y para futuros usos con un cliente propio.
        self._client = client

    @property
    def client(self) -> httpx.Client:
        return self._client if self._client is not None else get_client()

    def fetch(self, filters: dict[str, str]) -> list[dict[str, Any]]:
        """Consulta `GET /v1/farmacos` y devuelve la lista ya validada.

        `filters` debe venir ya validado por `FarmacoFilterSerializer`: aqui no
        se acepta nada que el cliente no haya podido comprobar antes.
        """
        response = self._request(filters)
        self._raise_for_status(response)
        return self._parse(response)

    def _request(self, filters: dict[str, str]) -> httpx.Response:
        try:
            # httpx se encarga del url-encoding de los parametros. Nunca se
            # concatena la query string a mano.
            return self.client.get(FARMACOS_ENDPOINT_PATH, params=filters)
        except httpx.TimeoutException as exc:
            self._report(exc, "Timeout consultando la API de farmacos")
            raise FarmacosAPITimeoutError from exc
        except httpx.ConnectError as exc:
            self._report(exc, "Error de conexion con la API de farmacos")
            raise FarmacosAPIConnectionError from exc
        except httpx.HTTPError as exc:
            self._report(exc, "Fallo de transporte con la API de farmacos")
            raise FarmacosAPIError from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        """Traduce el codigo HTTP externo a un error de dominio.

        Un `200` con lista vacia NO es un error: es "sin resultados".
        Un `404` NO significa "sin resultados": significa que el endpoint no
        existe, es decir, un problema de configuracion o de integracion.
        """
        status_code = response.status_code
        if status_code == httpx.codes.OK:
            return

        if status_code == httpx.codes.BAD_REQUEST:
            # Atribuible a los filtros que envio el cliente. No es ruido de
            # infraestructura, asi que no se reporta a Sentry.
            logger.info("La API de farmacos rechazo los filtros (400)")
            raise FarmacosAPIBadRequestError

        message = f"La API de farmacos respondio HTTP {status_code}"
        self._report(FarmacosAPIError(message), message)
        raise FarmacosAPIError

    def _parse(self, response: httpx.Response) -> list[dict[str, Any]]:
        try:
            payload = response.json()
        except ValueError as exc:
            # json.JSONDecodeError hereda de ValueError.
            self._report(exc, "La API de farmacos devolvio un JSON no parseable")
            raise FarmacosAPIResponseError from exc

        if not isinstance(payload, list):
            message = (
                "La API de farmacos devolvio "
                f"{type(payload).__name__} en lugar de una lista"
            )
            self._report(FarmacosAPIResponseError(message), message)
            raise FarmacosAPIResponseError

        serializer = FarmacoSerializer(data=payload, many=True)
        try:
            serializer.is_valid(raise_exception=True)
        except serializers.ValidationError as exc:
            self._report(exc, "La API de farmacos devolvio una estructura invalida")
            raise FarmacosAPIResponseError from exc

        # `validated_data` deja exactamente los cinco campos del contrato: si la
        # API externa anade campos nuevos, no se filtran hacia nuestro cliente.
        return [dict(item) for item in serializer.validated_data]

    @staticmethod
    def _report(exc: Exception, message: str) -> None:
        """Registra un fallo de integracion en logs y en Sentry.

        `capture_exception` es un no-op si Sentry no esta inicializado, que es
        el caso en desarrollo y en tests. No se registran ni la URL externa ni
        los filtros, que pueden contener terminos clinicos.
        """
        logger.error(message)
        sentry_sdk.capture_exception(exc)


class FarmacosService:
    """Punto de entrada de la funcionalidad de farmacos.

    Hoy delega directamente en el cliente HTTP. Cuando se anadan cache Redis,
    sincronizacion Celery o persistencia en PostgreSQL, se insertaran aqui y la
    view no tendra que cambiar.
    """

    def __init__(self, client: FarmacosAPIClient | None = None) -> None:
        self._client = client or FarmacosAPIClient()

    def list_farmacos(self, filters: dict[str, str]) -> list[dict[str, Any]]:
        return self._client.fetch(filters)
