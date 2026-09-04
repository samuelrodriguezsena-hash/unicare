"""Tareas Celery de la agenda.

Reparto de responsabilidades:

  * `dispatch_due_reminders`  periodica. Solo SELECCIONA lo que toca enviar y
    encola una tarea por recordatorio. Asi un fallo de envio no arrastra al
    resto del lote, y cada recordatorio tiene sus propios reintentos.
  * `send_reminder`           envia UN recordatorio, con reintentos.
  * `schedule_reminders_for_appointment` programa los avisos de una cita.

C-05: los reintentos son de Celery (`autoretry_for`, `max_retries`, backoff
exponencial). NO se persiste el contador de intentos, porque el DER no define
ninguna columna para ello.
"""

from __future__ import annotations

import logging

from celery import shared_task

from apps.appointments.models import Appointment, AppointmentReminder
from apps.appointments.services.reminders import ReminderService
from apps.core.services.notifications import NotificationError

logger = logging.getLogger(__name__)

MAX_REINTENTOS = 3


@shared_task(name="apps.appointments.tasks.dispatch_due_reminders")
def dispatch_due_reminders() -> int:
    """Encola el envio de los recordatorios cuyo momento ya llego.

    Devuelve cuantos ha encolado. No envia nada por si misma: si lo hiciera, un
    proveedor lento bloquearia el resto del lote y un fallo obligaria a
    reintentar recordatorios que ya se habian enviado.
    """
    pendientes = ReminderService.due()
    for reminder_id in pendientes:
        send_reminder.delay(reminder_id)

    if pendientes:
        logger.info("Encolados %s recordatorios", len(pendientes))
    return len(pendientes)


@shared_task(
    bind=True,
    name="apps.appointments.tasks.send_reminder",
    autoretry_for=(NotificationError,),
    max_retries=MAX_REINTENTOS,
    retry_backoff=True,
    retry_jitter=True,
)
def send_reminder(self, reminder_id: int) -> str:
    """Envia un recordatorio, con reintentos ante fallo del proveedor."""
    reminder = (
        AppointmentReminder.objects.select_related("appointment__patient")
        .filter(pk=reminder_id)
        .first()
    )
    if reminder is None:
        # Pudo borrarse al reprogramar la cita entre el encolado y el envio.
        logger.info("Recordatorio %s ya no existe; nada que enviar", reminder_id)
        return "missing"

    # En el ultimo intento el servicio marca FAILED antes de propagar; en los
    # anteriores deja el estado como esta, porque aun se va a reintentar.
    es_ultimo = self.request.retries >= MAX_REINTENTOS
    ReminderService().send(reminder, is_last_attempt=es_ultimo)
    return "sent"


@shared_task(name="apps.appointments.tasks.schedule_reminders_for_appointment")
def schedule_reminders_for_appointment(appointment_id: int) -> int:
    """Programa los recordatorios de una cita. Devuelve cuantos creo."""
    cita = (
        Appointment.objects.select_related("patient").filter(pk=appointment_id).first()
    )
    if cita is None:
        logger.info(
            "Cita %s ya no existe; no se programan recordatorios", appointment_id
        )
        return 0

    return len(ReminderService().schedule(cita))


@shared_task(name="apps.appointments.tasks.reschedule_reminders_for_appointment")
def reschedule_reminders_for_appointment(appointment_id: int) -> int:
    """Rehace los recordatorios pendientes tras reprogramar una cita."""
    cita = (
        Appointment.objects.select_related("patient").filter(pk=appointment_id).first()
    )
    if cita is None:
        return 0

    return len(ReminderService().reschedule(cita))
