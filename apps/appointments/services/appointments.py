"""Reglas de negocio de la agenda."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.db.models import Prefetch, QuerySet

from apps.appointments import tasks
from apps.appointments.choices import AppointmentStatus
from apps.appointments.models import Appointment, AppointmentReminder
from apps.appointments.services.priority import AppointmentPriorityService


class AppointmentService:
    """Alta, reprogramacion y cancelacion de citas."""

    def __init__(self, priority: AppointmentPriorityService | None = None) -> None:
        self._priority = priority or AppointmentPriorityService()

    @staticmethod
    def base_queryset() -> QuerySet[Appointment]:
        """Consulta de listado, sin N+1.

        `select_related` para el paciente; `prefetch_related` para los
        recordatorios, que se muestran en el detalle.
        """
        return Appointment.objects.select_related("patient").prefetch_related(
            Prefetch(
                "reminders",
                queryset=AppointmentReminder.objects.order_by("scheduled_at"),
            )
        )

    @transaction.atomic
    def create(self, datos: dict[str, Any]) -> Appointment:
        """Agenda una cita, pide una prioridad sugerida y programa los avisos.

        La sugerencia se pide DESPUES de crear la cita, no antes: si la IA no
        responde, la cita queda agendada igual. Agendar es la operacion
        clinica; priorizar es apoyo.
        """
        cita = Appointment.objects.create(**datos)
        self._priority.suggest(cita)
        self._encolar(tasks.schedule_reminders_for_appointment, cita.pk)
        return cita

    @transaction.atomic
    def update(self, cita: Appointment, datos: dict[str, Any]) -> Appointment:
        """Modifica o reprograma una cita.

        Si cambia la fecha, los recordatorios pendientes apuntan a un momento
        que ya no es el bueno, asi que se rehacen. Los ya enviados no se tocan.
        """
        reprogramada = (
            "scheduled_at" in datos and datos["scheduled_at"] != cita.scheduled_at
        )
        for campo, valor in datos.items():
            setattr(cita, campo, valor)
        cita.save()

        if reprogramada:
            self._encolar(tasks.reschedule_reminders_for_appointment, cita.pk)
        return cita

    @staticmethod
    def _encolar(tarea: Any, appointment_id: int) -> None:
        """Encola una tarea al confirmarse la transaccion.

        `on_commit` evita la condicion de carrera clasica: si se encolara de
        inmediato, el worker podria leer la cita antes de que la transaccion se
        confirme, y no encontrarla.
        """
        transaction.on_commit(lambda: tarea.delay(appointment_id))

    @staticmethod
    def cancel(cita: Appointment) -> Appointment:
        """Cancela la cita.

        Es idempotente. El DER no define ninguna maquina de estados para
        `APPOINTMENT.status`, asi que no se inventa una: no se prohiben
        transiciones que el contrato no prohibe.
        """
        if cita.status != AppointmentStatus.CANCELLED:
            cita.status = AppointmentStatus.CANCELLED
            cita.save(update_fields=["status", "updated_at", "updated_by"])
        return cita

    @staticmethod
    def reminders(cita: Appointment) -> QuerySet[AppointmentReminder]:
        return cita.reminders.order_by("scheduled_at")
