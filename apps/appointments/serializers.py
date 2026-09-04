"""Serializers de `appointments`."""

from __future__ import annotations

from rest_framework import serializers

from apps.appointments.choices import AppointmentPriority, AppointmentStatus
from apps.appointments.models import Appointment, AppointmentReminder


class AppointmentReminderSerializer(serializers.ModelSerializer):
    """Recordatorio de una cita.

    De solo lectura: los recordatorios los programa el sistema (FASE 11), no
    el cliente de la API.
    """

    class Meta:
        model = AppointmentReminder
        fields = (
            "reminder_id",
            "channel",
            "scheduled_at",
            "sent_at",
            "status",
            "failure_reason",
        )
        read_only_fields = fields


class AppointmentSerializer(serializers.ModelSerializer):
    """Lectura de una cita.

    `ai_priority_pending_validation` es derivado, no una columna: expone el
    estado del flujo de aprobacion (hay sugerencia de IA sin confirmar).
    """

    patient_name = serializers.SerializerMethodField()
    reminders = AppointmentReminderSerializer(many=True, read_only=True)
    ai_priority_pending_validation = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = (
            "appointment_id",
            "patient",
            "patient_name",
            "scheduled_at",
            "status",
            "reason",
            "priority",
            "priority_suggested_by_ai",
            "priority_final",
            "ai_priority_pending_validation",
            "reminders",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_patient_name(self, obj: Appointment) -> str:
        return f"{obj.patient.first_name} {obj.patient.last_name}"

    def get_ai_priority_pending_validation(self, obj: Appointment) -> bool:
        from apps.appointments.services.priority import AppointmentPriorityService

        return AppointmentPriorityService.is_pending_validation(obj)


class AppointmentWriteSerializer(serializers.ModelSerializer):
    """Alta y reprogramacion de una cita.

    `priority_suggested_by_ai` y `priority_final` NO son escribibles aqui: el
    primero lo escribe la IA y el segundo tiene su propio endpoint de
    confirmacion profesional (DEC-02). Si el cliente pudiera enviarlos, podria
    hacer pasar por validada una prioridad que nadie ha revisado.
    """

    class Meta:
        model = Appointment
        fields = ("patient", "scheduled_at", "status", "reason", "priority")

    def validate(self, attrs: dict) -> dict:
        # El DER declara `status` nullable, pero una cita recien agendada sin
        # estado no es util. Se aplica el default en la ENTRADA de la API, sin
        # endurecer el esquema.
        if self.instance is None and not attrs.get("status"):
            attrs["status"] = AppointmentStatus.SCHEDULED
        return attrs


class AppointmentPriorityConfirmSerializer(serializers.Serializer):
    """Confirmacion profesional de la prioridad de una cita."""

    priority_final = serializers.ChoiceField(choices=AppointmentPriority.choices)


class CalendarQuerySerializer(serializers.Serializer):
    """Parametros de la vista de calendario."""

    view = serializers.ChoiceField(choices=["day", "week", "month"], default="month")
    date = serializers.DateField(required=False)
    patient = serializers.IntegerField(required=False)
