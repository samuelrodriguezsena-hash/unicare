"""Resumen clinico asistido por IA.

Flujo exigido por la documentacion:

    Paciente -> historial estructurado -> servicio -> Gemini -> resumen -> API

Aqui se prepara el contexto y se persiste el resultado. La invocacion al SDK
vive en `apps.core.services.gemini`.

Privacidad: el historial que se envia a Gemini se acota a lo clinicamente
pertinente. NO se envian identificacion, telefono, email ni direccion del
paciente: el modelo no los necesita para redactar un resumen.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.core.services.gemini import GeminiService, ai_envelope
from apps.people.models import ClinicalHistory, Patient
from apps.people.services.patients import PatientService

# Tope de elementos enviados al modelo. Un historial largo no aporta mas
# calidad al resumen y si mas coste y mas exposicion de datos clinicos.
MAX_ENTRADAS = 30
MAX_NOTAS = 20


class ClinicalSummaryService:
    """Genera y persiste el resumen clinico de un paciente."""

    def __init__(self, gemini: GeminiService | None = None) -> None:
        self._gemini = gemini or GeminiService()

    @staticmethod
    def build_context(paciente: Patient, historial: ClinicalHistory) -> dict[str, Any]:
        """Historial estructurado, minimizado, listo para el prompt."""
        return {
            "edad": ClinicalSummaryService._edad(paciente),
            "patologias": [
                {
                    "nombre": asociacion.pathology.name,
                    "principal": bool(asociacion.is_primary),
                    "fecha_diagnostico": (
                        asociacion.diagnosis_date.isoformat()
                        if asociacion.diagnosis_date
                        else None
                    ),
                }
                for asociacion in paciente.pathologies.select_related("pathology")
            ],
            "entradas": [
                {
                    "tipo": entrada.entry_type,
                    "fecha": entrada.entry_date.isoformat(),
                    "descripcion": entrada.description,
                }
                for entrada in historial.entries.order_by("-entry_date")[:MAX_ENTRADAS]
            ],
            "notas": [
                nota.text
                for nota in historial.notes.order_by("-created_at")[:MAX_NOTAS]
            ],
        }

    @staticmethod
    def _edad(paciente: Patient) -> int | None:
        if paciente.date_of_birth is None:
            return None
        hoy = timezone.localdate()
        cumplido = (hoy.month, hoy.day) >= (
            paciente.date_of_birth.month,
            paciente.date_of_birth.day,
        )
        return hoy.year - paciente.date_of_birth.year - (0 if cumplido else 1)

    def generate(self, paciente: Patient) -> dict[str, Any]:
        """Genera el resumen, lo persiste y lo devuelve etiquetado.

        `CLINICAL_HISTORY.last_ai_summary` es una CACHE del ultimo resumen: el
        DER no define ningun estado de aprobacion para el (C-06), asi que
        guardarlo no equivale a haberlo validado. La respuesta lo deja claro.
        """
        historial = PatientService.clinical_history(paciente)
        contexto = self.build_context(paciente, historial)

        resumen = self._gemini.generate_clinical_summary(contexto)

        historial.last_ai_summary = resumen
        historial.last_ai_summary_at = timezone.now()
        historial.save(
            update_fields=[
                "last_ai_summary",
                "last_ai_summary_at",
                "updated_at",
                "updated_by",
            ]
        )

        return ai_envelope(
            {
                "summary": resumen,
                "generated_at": historial.last_ai_summary_at.isoformat(),
                "clinical_history_id": historial.pk,
            }
        )
