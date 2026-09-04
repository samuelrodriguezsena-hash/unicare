"""Sugerencia de tratamiento asistida por IA.

Flujo exigido por la documentacion:

    1. se selecciona una patologia del historial del paciente;
    2. se obtiene el contexto clinico permitido;
    3. se construye un prompt estructurado;
    4. se envia a Gemini;
    5. Gemini devuelve familias farmacologicas y principios activos;
    6. se devuelve como SUGERENCIA.

C-06 / DEC-07: **la sugerencia NO se persiste.** El DER no define ninguna
columna ni tabla donde guardarla, ni su estado de aprobacion, y no se crean
tablas arbitrarias. El acto de aprobacion es que un profesional decida crear un
`TREATMENT_PLAN_MEDICATION` a partir de ella.

Limitacion conocida: no queda historial de sugerencias rechazadas.
"""

from __future__ import annotations

from typing import Any

from apps.core.services.gemini import GeminiService, ai_envelope
from apps.people.models import PatientPathology

# Entradas recientes del historial que acompanan a la patologia. Suficiente
# contexto para la sugerencia, sin volcar el historial completo al modelo.
MAX_ENTRADAS = 10


class TreatmentSuggestionService:
    """Sugerencias farmacologicas preliminares para una patologia."""

    def __init__(self, gemini: GeminiService | None = None) -> None:
        self._gemini = gemini or GeminiService()

    @staticmethod
    def build_context(asociacion: PatientPathology) -> dict[str, Any]:
        """Contexto clinico permitido.

        Solo lo pertinente para la sugerencia. NO se envian datos de contacto
        ni identificacion del paciente: el modelo no los necesita.
        """
        paciente = asociacion.patient
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
            "patologia": asociacion.pathology.name,
            "es_patologia_principal": bool(asociacion.is_primary),
            "fecha_diagnostico": (
                asociacion.diagnosis_date.isoformat()
                if asociacion.diagnosis_date
                else None
            ),
            "notas_de_la_patologia": asociacion.notes,
            "otras_patologias": [
                otra.pathology.name
                for otra in paciente.pathologies.select_related("pathology")
                if otra.pk != asociacion.pk
            ],
            "entradas_recientes": entradas,
        }

    def suggest(self, asociacion: PatientPathology) -> dict[str, Any]:
        """Devuelve la sugerencia etiquetada. No persiste nada."""
        contexto = self.build_context(asociacion)
        sugerencia = self._gemini.suggest_treatment(contexto)

        return ai_envelope(
            {
                "patient": asociacion.patient_id,
                "pathology": asociacion.pathology_id,
                "pathology_name": asociacion.pathology.name,
                "familias_farmacologicas": sugerencia["familias_farmacologicas"],
                "principios_activos": sugerencia["principios_activos"],
                "persisted": False,
            }
        )
