"""Modelos de `appointments`: agenda y recordatorios.

Entidades del DER implementadas aqui:

    APPOINTMENT, APPOINTMENT_REMINDER
"""

from __future__ import annotations

from django.db import models

from apps.appointments.choices import (
    AppointmentPriority,
    AppointmentStatus,
    ReminderChannel,
    ReminderStatus,
)
from apps.core.choices import ENUM_MAX_LENGTH
from apps.core.models import Auditor


class Appointment(Auditor):
    """Entidad `APPOINTMENT` del DER.

    El DER define TRES columnas relacionadas con la prioridad. DEC-02 fija su
    semantica y las mantiene independientes:

      * `priority`                 enum operativo de la cita.
      * `priority_suggested_by_ai` salida de Gemini. Es lo UNICO que escribe la
                                   IA. Vacio + `priority_final` vacio = la
                                   sugerencia sigue pendiente de validacion.
      * `priority_final`           valor confirmado por un profesional. Solo se
                                   escribe desde la accion explicita de
                                   validacion, nunca automaticamente.
    """

    appointment_id = models.BigAutoField(primary_key=True, db_column="appointment_id")
    patient = models.ForeignKey(
        "people.Patient",
        on_delete=models.PROTECT,
        db_column="patient_id",
        related_name="appointments",
    )
    scheduled_at = models.DateTimeField(db_column="scheduled_at")
    status = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=AppointmentStatus.choices,
        null=True,
        blank=True,
        db_column="status",
    )
    reason = models.TextField(null=True, blank=True, db_column="reason")
    priority = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=AppointmentPriority.choices,
        null=True,
        blank=True,
        db_column="priority",
    )
    # varchar(30) en el DER, NO enum: la respuesta cruda de la IA se guarda tal
    # cual, sin CheckConstraint que la restrinja.
    priority_suggested_by_ai = models.CharField(
        max_length=30, null=True, blank=True, db_column="priority_suggested_by_ai"
    )
    priority_final = models.CharField(
        max_length=30, null=True, blank=True, db_column="priority_final"
    )

    class Meta:
        db_table = "appointment"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=AppointmentStatus.values)
                | models.Q(status__isnull=True),
                name="ck_appointment_status",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__in=AppointmentPriority.values)
                | models.Q(priority__isnull=True),
                name="ck_appointment_priority",
            ),
        ]
        # DEC-05: soportan el calendario (dia/semana/mes) y la agenda por
        # paciente sin alterar el contrato del DER.
        indexes = [
            models.Index(fields=["scheduled_at"], name="ix_appointment_scheduled_at"),
            models.Index(
                fields=["patient", "scheduled_at"], name="ix_appointment_patient_date"
            ),
        ]

    def __str__(self) -> str:
        return f"cita:{self.pk} {self.scheduled_at:%Y-%m-%d %H:%M}"


class AppointmentReminder(models.Model):
    """Entidad `APPOINTMENT_REMINDER` del DER.

    NO hereda de `Auditor`: el DER no le define `created_at`, `updated_at`,
    `created_by` ni `updated_by`, y no se le anaden (D-02).

    C-05: el DER tampoco define contador de reintentos. Los reintentos viven en
    la capa Celery (`autoretry_for`, `max_retries`, backoff); aqui solo queda el
    resultado final en `status`, `sent_at` y `failure_reason`.
    """

    reminder_id = models.BigAutoField(primary_key=True, db_column="reminder_id")
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        db_column="appointment_id",
        related_name="reminders",
    )
    channel = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=ReminderChannel.choices,
        null=True,
        blank=True,
        db_column="channel",
    )
    scheduled_at = models.DateTimeField(db_column="scheduled_at")
    sent_at = models.DateTimeField(null=True, blank=True, db_column="sent_at")
    status = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=ReminderStatus.choices,
        null=True,
        blank=True,
        db_column="status",
    )
    failure_reason = models.TextField(null=True, blank=True, db_column="failure_reason")

    class Meta:
        db_table = "appointment_reminder"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(channel__in=ReminderChannel.values)
                | models.Q(channel__isnull=True),
                name="ck_appointment_reminder_channel",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=ReminderStatus.values)
                | models.Q(status__isnull=True),
                name="ck_appointment_reminder_status",
            ),
        ]
        # DEC-05: la tarea periodica selecciona por (status, scheduled_at).
        indexes = [
            models.Index(
                fields=["status", "scheduled_at"], name="ix_reminder_status_date"
            ),
        ]

    def __str__(self) -> str:
        return f"recordatorio:{self.pk} {self.status}"
