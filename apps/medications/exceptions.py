"""Errores de la integracion con la API externa de farmacos.

Se apoyan en la jerarquia de `apps.core.exceptions`, de forma que
`api_exception_handler` ya sabe traducirlos a HTTP sin tocar la view:

    FarmacosAPIBadRequestError   -> 400  la API externa rechazo los filtros
    FarmacosAPITimeoutError      -> 504  no respondio a tiempo
    FarmacosAPIConnectionError   -> 502  no se pudo establecer la conexion
    FarmacosAPIResponseError     -> 502  respondio algo que no entendemos
    FarmacosAPIError             -> 502  cualquier otro fallo de integracion

Ninguno de estos mensajes expone la URL externa, cabeceras ni stack traces:
el detalle tecnico va a logs y a Sentry, no al cliente.
"""

from __future__ import annotations

from apps.core.exceptions import (
    DomainError,
    ExternalServiceError,
    ExternalServiceTimeoutError,
)


class FarmacosAPIError(ExternalServiceError):
    """Fallo generico al consultar la API externa de farmacos."""

    default_detail = "No fue posible consultar el servicio de farmacos."
    code = "farmacos_api_error"


class FarmacosAPITimeoutError(ExternalServiceTimeoutError):
    """La API externa no respondio dentro del timeout configurado."""

    default_detail = "El servicio de farmacos tardo demasiado en responder."
    code = "farmacos_api_timeout"


class FarmacosAPIConnectionError(FarmacosAPIError):
    """No se pudo establecer la conexion con la API externa."""

    default_detail = "No fue posible conectar con el servicio de farmacos."
    code = "farmacos_api_connection_error"


class FarmacosAPIResponseError(FarmacosAPIError):
    """La API externa respondio algo que no cumple el contrato documentado.

    Cubre tanto un JSON no parseable como una estructura inesperada (que no sea
    una lista de objetos con los cinco campos). Es un error de integracion,
    NUNCA un resultado valido.
    """

    default_detail = "El servicio de farmacos devolvio una respuesta invalida."
    code = "farmacos_api_response_error"


class FarmacosAPIBadRequestError(DomainError):
    """La API externa rechazo los filtros enviados (HTTP 400).

    Se propaga como 400 y NO como 502: los filtros los aporta el cliente, asi
    que el problema es atribuible a la peticion entrante. Por el mismo motivo
    no se reporta a Sentry: es un error esperable de validacion, no un fallo de
    infraestructura.
    """

    status_code = 400
    default_detail = "El servicio de farmacos rechazo los filtros indicados."
    code = "farmacos_api_bad_request"
