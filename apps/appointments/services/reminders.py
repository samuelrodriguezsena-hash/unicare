"""Programacion y envio de recordatorios de citas.

C-05: el DER NO define ningun contador de reintentos en `APPOINTMENT_REMINDER`,
y no se le anade. Los reintentos viven en la capa Celery; aqui solo queda el
resultado final en las columnas que si existen: `status`, `sent_at` y
`failure_reason`.

Limitacion documentada: no hay trazabilidad persistida del NUMERO de intentos,
solo la que quede en los logs y en Sentry.
"""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.appointments.choices import ReminderChannel, ReminderStatus
from apps.appointments.models import Appointment, AppointmentReminder
from apps.core.services.notifications import (
    Notification,
    NotificationError,
    NotificationService,
)

logger = logging.getLogger(__name__)

MAX_FAILURE_REASON = 1000


class ReminderService:
    """Programa recordatorios y gestiona su envio."""

    def __init__(self, notifications: NotificationService | None = None) -> None:
        self._notifications = notifications or NotificationService()

    # ------------------------------------------------------------------
    # Programacion
    # ------------------------------------------------------------------
    @staticmethod
    def choose_channel(appointment: Appointment) -> str | None:
        """Canal segun el contacto disponible del paciente.

        Devuelve `None` si el paciente no tiene ningun contacto: programar un
        recordatorio que no se puede entregar solo genera fallos.

        DEC-29: el DER declara `channel` nullable y no dice como elegirlo. Se
        prefiere email por ser el unico canal que no tiene coste por mensaje;
        el SMS queda como alternativa cuando no hay email.
        """
        paciente = appointment.patient
        if paciente.email:
            return ReminderChannel.EMAIL
        if paciente.phone:
            return ReminderChannel.SMS
        return None

    @staticmethod
    def offsets() -> list[int]:
        """Horas antes de la cita a las que se avisa. Por defecto 48 y 24."""
        return list(settings.REMINDER_OFFSETS_HOURS)

    def schedule(self, appointment: Appointment) -> list[AppointmentReminder]:
        """Crea los recordatorios pendientes de una cita.

        Es idempotente: no duplica un recordatorio ya programado para el mismo
        instante. El DER no declara una restriccion unica sobre
        (appointment, scheduled_at), asi que la idempotencia se garantiza aqui.

        Se omiten los avisos cuyo momento ya paso: no tiene sentido programar
        un recordatorio de -48h para una cita que es manana.
        """
        canal = self.choose_channel(appointment)
        if canal is None:
            logger.info(
                "Cita %s sin recordatorios: el paciente no tiene contacto",
                appointment.pk,
            )
            return []

        ahora = timezone.now()
        ya_programados = set(
            appointment.reminders.values_list("scheduled_at", flat=True)
        )

        creados = []
        for horas in self.offsets():
            momento = appointment.scheduled_at - timedelta(hours=horas)
            if momento <= ahora or momento in ya_programados:
                continue
            creados.append(
                AppointmentReminder.objects.create(
                    appointment=appointment,
                    channel=canal,
                    scheduled_at=momento,
                    status=ReminderStatus.PENDING,
                )
            )
        return creados

    @staticmethod
    def clear_pending(appointment: Appointment) -> int:
        """Descarta los recordatorios aun no enviados.

        Se usa al reprogramar una cita: los avisos pendientes apuntan a una
        fecha que ya no es la buena. Los ya enviados NO se tocan: son historia
        de lo que el paciente recibio.
        """
        borrados, _ = appointment.reminders.filter(
            status=ReminderStatus.PENDING
        ).delete()
        return borrados

    def reschedule(self, appointment: Appointment) -> list[AppointmentReminder]:
        self.clear_pending(appointment)
        return self.schedule(appointment)

    # ------------------------------------------------------------------
    # Envio
    # ------------------------------------------------------------------
    @staticmethod
    def due(now: timezone.datetime | None = None) -> list[int]:
        """IDs de los recordatorios pendientes cuyo momento ya llego."""
        return list(
            AppointmentReminder.objects.filter(
                status=ReminderStatus.PENDING,
                scheduled_at__lte=now or timezone.now(),
            )
            .order_by("scheduled_at")
            .values_list("pk", flat=True)
        )

    @staticmethod
    def build_notification(reminder: AppointmentReminder) -> Notification:
        paciente = reminder.appointment.patient
        destinatario = (
            paciente.email
            if reminder.channel == ReminderChannel.EMAIL
            else paciente.phone
        )
        cuando = timezone.localtime(reminder.appointment.scheduled_at)
        return Notification(
            channel=reminder.channel,
            recipient=destinatario or "",
            subject="Recordatorio de cita",
            # Sin datos clinicos: un recordatorio no debe revelar el motivo de
            # la consulta ni la patologia por un canal no seguro.
            body=(
                f"{paciente.first_name}, le recordamos su cita del "
                f"{cuando:%d/%m/%Y} a las {cuando:%H:%M}."
            ),
        )

    def send(
        self, reminder: AppointmentReminder, *, is_last_attempt: bool
    ) -> AppointmentReminder:
        """Envia un recordatorio y registra el resultado.

        `is_last_attempt` lo aporta la tarea Celery a partir de los reintentos
        que le quedan. Solo en el ultimo intento se marca FAILED: hacerlo antes
        daria por perdido algo que aun se va a reintentar.

        Idempotente: un recordatorio ya enviado no se reenvia.
        """
        if reminder.status == ReminderStatus.SENT:
            return reminder

        try:
            self._notifications.send(self.build_notification(reminder))
        except NotificationError as exc:
            if is_last_attempt:
                reminder.status = ReminderStatus.FAILED
                reminder.failure_reason = str(exc)[:MAX_FAILURE_REASON]
                reminder.save(update_fields=["status", "failure_reason"])
                logger.error("Recordatorio %s fallido definitivamente", reminder.pk)
            raise

        reminder.status = ReminderStatus.SENT
        reminder.sent_at = timezone.now()
        reminder.failure_reason = None
        reminder.save(update_fields=["status", "sent_at", "failure_reason"])
        return reminder
