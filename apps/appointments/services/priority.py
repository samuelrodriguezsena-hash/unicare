"""Priorizacion de citas asistida por IA.

DEC-02 fija la semantica de las tres columnas de prioridad del DER:

  * `priority`                 enum operativo de la cita.
  * `priority_suggested_by_ai` UNICO campo que escribe la IA.
  * `priority_final`           valor confirmado por un profesional.

Vacio en `priority_final` = la sugerencia sigue pendiente de validacion. Es el
flujo de aprobacion que exige la documentacion, materializado sobre columnas
que ya existen (C-06), sin crear ninguna tabla.
"""

from __future__ import annotations

import logging
from typing import Any

from apps.appointments.choices import AppointmentPriority
from apps.appointments.models import Appointment
from apps.core.exceptions import GeminiNotConfiguredError, GeminiServiceError
from apps.core.services.gemini import GeminiService

logger = logging.getLogger(__name__)

# Entradas recientes del historial que acompanan al motivo de consulta.
MAX_ENTRADAS = 5


class AppointmentPriorityService:
    """Sugiere una prioridad y registra la confirmacion profesional."""

    def __init__(self, gemini: GeminiService | None = None) -> None:
        self._gemini = gemini or GeminiService()

    @staticmethod
    def build_context(cita: Appointment) -> dict[str, Any]:
        """Motivo de consulta e historial reciente relevante.

        Privacidad: como en el resto de la integracion con IA, no se envian
        identificacion ni datos de contacto del paciente (DEC-25).
        """
        paciente = cita.patient
        historial = getattr(paciente, "clinical_history", None)

        entradas = []
        if historial is not None:
            entradas = [
                {
                    "tipo": entrada.entry_type,
                    "fecha": entrada.entry_date.isoformat(),
                    "descripcion": entrada.description,
                }
                for entrada in historial.entries.order_by("-entry_date")[:MAX_ENTRADAS]
            ]

        return {
            "motivo_de_consulta": cita.reason,
            "patologias": [
                asociacion.pathology.name
                for asociacion in paciente.pathologies.select_related("pathology")
            ],
            "entradas_recientes": entradas,
        }

    def suggest(self, cita: Appointment) -> str | None:
        """Sugiere una prioridad y la guarda en `priority_suggested_by_ai`.

        Devuelve `None` si no fue posible sugerir nada.

        Un fallo de la IA NO impide agendar la cita. Es lo contrario de lo que
        se hace al asociar un medicamento (DEC-21): alli el dato externo forma
        parte de la integridad del registro; aqui la sugerencia es puramente
        orientativa, y bloquear una cita clinica por una caida del proveedor de
        IA seria desproporcionado.

        Se captura tambien `GeminiNotConfiguredError`: un entorno SIN
        `GEMINI_API_KEY` es un despliegue legitimo, y en el las citas tienen
        que poder agendarse igual. Los endpoints que piden IA de forma
        explicita (resumen clinico, sugerencia de tratamiento) SI devuelven 503
        en ese caso, porque alli la IA es el objeto de la peticion.
        """
        try:
            prioridad = self._gemini.prioritize_appointment(
                self.build_context(cita), list(AppointmentPriority.values)
            )
        except (GeminiServiceError, GeminiNotConfiguredError):
            # Ya queda registrado en logs y Sentry dentro de GeminiService.
            logger.info("Cita %s agendada sin prioridad sugerida", cita.pk)
            return None

        cita.priority_suggested_by_ai = prioridad
        cita.save(
            update_fields=[
                "priority_suggested_by_ai",
                "updated_at",
                "updated_by",
            ]
        )
        return prioridad

    @staticmethod
    def confirm(cita: Appointment, prioridad: str) -> Appointment:
        """Registra la prioridad decidida por un profesional.

        Escribe `priority_final` y tambien `priority`, el enum operativo con el
        que trabaja la agenda: DEC-02 impide que la IA escriba esos campos, no
        que lo haga un profesional de forma explicita.
        """
        cita.priority_final = prioridad
        cita.priority = prioridad
        cita.save(
            update_fields=["priority_final", "priority", "updated_at", "updated_by"]
        )
        return cita

    @staticmethod
    def is_pending_validation(cita: Appointment) -> bool:
        """Hay una sugerencia de IA que ningun profesional ha validado aun."""
        return bool(cita.priority_suggested_by_ai) and not cita.priority_final
