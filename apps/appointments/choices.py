"""Dominios enumerados de `appointments`.

Valores fijados en docs/DECISIONS.md seccion 4 (DEC-03). Las prioridades y los
canales provienen literalmente de la documentacion funcional.
"""

from __future__ import annotations

from django.db import models


class AppointmentStatus(models.TextChoices):
    SCHEDULED = "SCHEDULED", "Agendada"
    CONFIRMED = "CONFIRMED", "Confirmada"
    COMPLETED = "COMPLETED", "Atendida"
    CANCELLED = "CANCELLED", "Cancelada"
    NO_SHOW = "NO_SHOW", "No asistio"


class AppointmentPriority(models.TextChoices):
    URGENT = "URGENT", "Urgente"
    ROUTINE_CONTROL = "ROUTINE_CONTROL", "Control de Rutina"
    POST_OPERATIVE = "POST_OPERATIVE", "Post-operatorio"


class ReminderChannel(models.TextChoices):
    EMAIL = "EMAIL", "Email"
    SMS = "SMS", "SMS"


class ReminderStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    SENT = "SENT", "Enviado"
    FAILED = "FAILED", "Fallido"
