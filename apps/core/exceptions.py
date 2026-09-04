"""Errores de dominio y manejo consistente de errores de la API.

Regla del proyecto: los errores de servicios externos se traducen a errores de
dominio SIN exponer detalles sensibles, y en produccion nunca se devuelve un
stack trace.
"""

from __future__ import annotations

import logging
from typing import Any

from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Error de negocio de UniCare."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Error de dominio."
    code = "domain_error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.default_detail
        super().__init__(self.detail)


class ExternalServiceError(DomainError):
    """Fallo de una integracion externa (API de farmacos, Gemini).

    El detalle tecnico se registra en logs y Sentry; al cliente solo se le
    devuelve un mensaje generico.
    """

    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "El servicio externo no esta disponible en este momento."
    code = "external_service_error"


class ExternalServiceTimeoutError(ExternalServiceError):
    """El servicio externo no respondio dentro del timeout configurado."""

    status_code = status.HTTP_504_GATEWAY_TIMEOUT
    default_detail = "El servicio externo tardo demasiado en responder."
    code = "external_service_timeout"


class GeminiServiceError(ExternalServiceError):
    """Fallo al invocar el servicio de IA."""

    default_detail = "El servicio de inteligencia artificial no esta disponible."
    code = "gemini_service_error"


class GeminiResponseError(GeminiServiceError):
    """El modelo respondio algo que no cumple el formato esperado.

    Es un error de integracion, NUNCA un resultado valido: devolver texto libre
    como si fuera una sugerencia estructurada seria peor que fallar.
    """

    default_detail = (
        "El servicio de inteligencia artificial devolvio una respuesta invalida."
    )
    code = "gemini_response_error"


class GeminiNotConfiguredError(DomainError):
    """No hay `GEMINI_API_KEY` configurada.

    Es un problema de despliegue, no del cliente ni del proveedor, y por eso se
    distingue de un fallo del servicio externo.
    """

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = (
        "La funcionalidad de inteligencia artificial no esta configurada en "
        "este entorno."
    )
    code = "gemini_not_configured"


class ConflictError(DomainError):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "La operacion entra en conflicto con el estado actual."
    code = "conflict"


class NotFoundError(DomainError):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "El recurso solicitado no existe."
    code = "not_found"


def api_exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    """Handler de excepciones de DRF.

    Traduce los `DomainError` a respuestas HTTP coherentes y delega el resto en
    el handler estandar de DRF (que ya cubre 400/401/403/404/405/429).
    """
    if isinstance(exc, DomainError):
        if isinstance(exc, ExternalServiceError):
            logger.warning("Fallo de integracion externa: %s", exc.detail)
        return Response(
            {"detail": exc.detail, "code": exc.code},
            status=exc.status_code,
        )

    return drf_exception_handler(exc, context)
