"""Envio de notificaciones.

El dominio de citas NO conoce ningun proveedor: habla con `NotificationService`,
que delega en un backend intercambiable. Integrar email o SMS de verdad mas
adelante consiste en escribir un backend y cambiar `NOTIFICATION_BACKEND`, sin
tocar `appointments`.

Hoy solo existe `LoggingNotificationBackend`, que registra el envio sin
contactar con nadie. Es deliberado: la documentacion pide que la arquitectura
PERMITA integrar email y SMS despues, no que se integren ahora, y no hay ningun
proveedor contratado que se pueda configurar sin inventarlo.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Fallo al entregar una notificacion.

    Es la excepcion que los backends deben lanzar y la que dispara los
    reintentos de Celery.
    """


@dataclass(frozen=True)
class Notification:
    """Mensaje a entregar, independiente del proveedor."""

    channel: str
    recipient: str
    subject: str
    body: str


class NotificationBackend(ABC):
    """Contrato que debe cumplir cualquier proveedor."""

    @abstractmethod
    def send(self, notification: Notification) -> None:
        """Entrega el mensaje o lanza `NotificationError`."""


class LoggingNotificationBackend(NotificationBackend):
    """Backend por defecto: deja constancia y no envia nada.

    Privacidad: se registran canal y asunto, NUNCA el cuerpo ni el
    destinatario completo. Un log de recordatorios clinicos no debe permitir
    reconstruir quien tiene cita ni por que.
    """

    def send(self, notification: Notification) -> None:
        logger.info(
            "Notificacion %s preparada (asunto: %s)",
            notification.channel,
            notification.subject,
        )


class NotificationService:
    """Punto de entrada unico para enviar notificaciones."""

    def __init__(self, backend: NotificationBackend | None = None) -> None:
        self._backend = backend

    @property
    def backend(self) -> NotificationBackend:
        if self._backend is None:
            self._backend = import_string(settings.NOTIFICATION_BACKEND)()
        return self._backend

    def send(self, notification: Notification) -> None:
        self.backend.send(notification)
