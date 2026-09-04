"""Serializacion de citas como eventos de calendario.

Es una REPRESENTACION ALTERNATIVA del mismo modelo: no se anade ninguna columna
ni tabla para soportarla. La estructura de salida sigue la convencion habitual
de las librerias de calendario de frontend (`id`, `title`, `start`,
`extendedProps`).

LIMITACION DEL DER: `APPOINTMENT` define `scheduled_at` pero NO define duracion
ni hora de fin. Por eso los eventos no llevan `end`: inventar una duracion por
defecto seria anadir informacion clinica que el contrato no contiene. Las
librerias de calendario representan correctamente un evento con solo `start`.
"""

from __future__ import annotations

import calendar as calendario_py
from datetime import date, datetime, timedelta
from typing import Any

from django.db.models import QuerySet
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.core.exceptions import DomainError

VISTAS = ("day", "week", "month")


class InvalidCalendarViewError(DomainError):
    status_code = 400
    default_detail = "La vista debe ser 'day', 'week' o 'month'."
    code = "invalid_calendar_view"


class CalendarService:
    """Rangos de fechas y eventos para la agenda."""

    @staticmethod
    def range_for(vista: str, dia: date) -> tuple[datetime, datetime]:
        """Intervalo [inicio, fin) de la vista pedida.

        Se calcula en la zona horaria activa y se devuelve con zona, para que
        la comparacion contra `scheduled_at` (timestamptz) sea correcta.
        """
        if vista == "day":
            inicio, fin = dia, dia + timedelta(days=1)
        elif vista == "week":
            # La semana empieza en lunes.
            inicio = dia - timedelta(days=dia.weekday())
            fin = inicio + timedelta(days=7)
        elif vista == "month":
            inicio = dia.replace(day=1)
            ultimo = calendario_py.monthrange(dia.year, dia.month)[1]
            fin = inicio + timedelta(days=ultimo)
        else:
            raise InvalidCalendarViewError

        zona = timezone.get_current_timezone()
        return (
            timezone.make_aware(datetime.combine(inicio, datetime.min.time()), zona),
            timezone.make_aware(datetime.combine(fin, datetime.min.time()), zona),
        )

    @staticmethod
    def to_event(cita: Appointment) -> dict[str, Any]:
        """Convierte una cita en un evento de calendario."""
        paciente = cita.patient
        return {
            "id": cita.pk,
            "title": f"{paciente.first_name} {paciente.last_name}",
            "start": cita.scheduled_at.isoformat(),
            "extendedProps": {
                "patient": paciente.pk,
                "status": cita.status,
                "priority": cita.priority,
                "priority_final": cita.priority_final,
                "priority_suggested_by_ai": cita.priority_suggested_by_ai,
                "reason": cita.reason,
            },
        }

    @classmethod
    def events(cls, citas: QuerySet[Appointment]) -> list[dict[str, Any]]:
        return [cls.to_event(cita) for cita in citas]
