"""Observabilidad: integracion con Sentry.

Esta en un modulo propio, y no dentro de las settings, para que la logica de
saneado pueda probarse sin inicializar Sentry.

REGLA DE PRIVACIDAD: este sistema maneja informacion clinica. Un servicio de
observabilidad es un tercero, y lo que se le manda sale de nuestra
infraestructura. Por eso el saneado es agresivo por defecto:

  * NUNCA se envia el cuerpo de la peticion. `sentry-sdk` lo captura por
    defecto (`max_request_body_size="medium"`), y ese cuerpo contiene
    diagnosticos, notas clinicas y datos de contacto de pacientes.
  * NUNCA se envian cabeceras, cookies ni credenciales.
  * Del usuario solo se envia su ID, nunca su nombre ni su email.

Lo que SI se envia: excepciones, trazas, el endpoint, y el identificador del
usuario responsable. Suficiente para diagnosticar sin exfiltrar historiales.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# Claves cuyo valor no debe salir nunca, comparadas en minusculas y por
# coincidencia parcial: cubre `gemini_api_key`, `HTTP_AUTHORIZATION`, etc.
CLAVES_SENSIBLES: tuple[str, ...] = (
    "password",
    "passwd",
    "secret",
    "token",
    "authorization",
    "api_key",
    "apikey",
    "session",
    "cookie",
    "csrf",
    "dsn",
)

# Campos con contenido clinico o identificativo del paciente.
CLAVES_CLINICAS: tuple[str, ...] = (
    "identification_number",
    "first_name",
    "last_name",
    "date_of_birth",
    "phone",
    "email",
    "address",
    "description",
    "clinical_note",
    "notes",
    "reason",
    "text",
    "last_ai_summary",
    "old_values",
    "new_values",
)

REDACTADO = "[redactado]"


def _es_sensible(clave: str) -> bool:
    minuscula = str(clave).lower()
    return any(patron in minuscula for patron in CLAVES_SENSIBLES + CLAVES_CLINICAS)


def scrub(valor: Any) -> Any:
    """Recorre una estructura y redacta lo que no debe salir."""
    if isinstance(valor, dict):
        return {
            clave: REDACTADO if _es_sensible(clave) else scrub(contenido)
            for clave, contenido in valor.items()
        }
    if isinstance(valor, list):
        return [scrub(item) for item in valor]
    if isinstance(valor, tuple):
        return tuple(scrub(item) for item in valor)
    return valor


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    """Sanea cada evento antes de que salga hacia Sentry.

    Es la ultima barrera: aunque una integracion capture algo de mas, aqui se
    elimina.
    """
    peticion = event.get("request")
    if isinstance(peticion, dict):
        # El cuerpo puede contener un historial clinico entero.
        peticion.pop("data", None)
        peticion.pop("cookies", None)
        peticion.pop("headers", None)
        if isinstance(peticion.get("query_string"), str):
            peticion["query_string"] = ""

    # Solo el ID del usuario: ni nombre, ni email, ni IP.
    event["user"] = {"id": _usuario_actual()}

    for seccion in ("extra", "contexts", "tags"):
        if isinstance(event.get(seccion), dict):
            event[seccion] = scrub(event[seccion])

    # Las migas de pan tambien viajan a Sentry. Los logs de la aplicacion
    # registran identificadores, no contenido clinico, pero su `data` puede
    # traer estructuras completas segun la integracion.
    migas = event.get("breadcrumbs")
    if isinstance(migas, dict) and isinstance(migas.get("values"), list):
        for miga in migas["values"]:
            if isinstance(miga, dict) and isinstance(miga.get("data"), dict):
                miga["data"] = scrub(miga["data"])

    return event


def _usuario_actual() -> str | None:
    """ID del usuario responsable, si la operacion viene de una peticion."""
    try:
        from apps.core.context import get_current_user

        usuario = get_current_user()
        return str(usuario.pk) if usuario is not None else None
    except Exception:  # pragma: no cover - nunca debe romper el envio
        return None


def sentry_options(dsn: str) -> dict[str, Any]:
    """Opciones de inicializacion. Separadas para poder verificarlas."""
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    return {
        "dsn": dsn,
        "environment": os.environ.get("SENTRY_ENVIRONMENT", "production"),
        "release": os.environ.get("SENTRY_RELEASE") or None,
        "integrations": [
            DjangoIntegration(),
            # Los fallos de tareas Celery tambien se reportan.
            CeleryIntegration(),
            # `logger.error(...)` genera evento; los warnings solo migas.
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        "traces_sample_rate": float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        # Sin esto, `sentry-sdk` envia cabeceras, cookies e IP del usuario.
        "send_default_pii": False,
        # CRITICO: el valor por defecto es "medium", que SI envia el cuerpo de
        # la peticion. Con informacion clinica eso es inaceptable.
        "max_request_body_size": "never",
        "before_send": before_send,
    }


def init_sentry() -> bool:
    """Inicializa Sentry si hay DSN. Devuelve si quedo activo.

    Sin `SENTRY_DSN` es un no-op: los entornos sin observabilidad configurada
    funcionan igual, y `capture_exception` no hace nada.
    """
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("Sentry desactivado: no hay SENTRY_DSN configurado")
        return False

    import sentry_sdk

    sentry_sdk.init(**sentry_options(dsn))
    return True
