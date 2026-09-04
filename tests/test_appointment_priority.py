"""Tests del servicio real de priorizacion (FASE 10).

`tests/test_appointments_api.py` sustituye este servicio entero para probar la
agenda; aqui se prueba el servicio de verdad, con un doble de `GeminiService`.
Asi ninguna de las dos capas queda sin ejercitar.

Ninguna llamada real al SDK. Requiere PostgreSQL.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.appointments.choices import AppointmentPriority
from apps.appointments.models import Appointment
from apps.appointments.services.priority import AppointmentPriorityService
from apps.core.exceptions import (
    GeminiNotConfiguredError,
    GeminiResponseError,
    GeminiServiceError,
)
from apps.core.services.gemini import GeminiService
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Pathology,
    Patient,
    PatientPathology,
)
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db


class GeminiFalso(GeminiService):
    """Doble que responde lo que se le indique, sin tocar el SDK."""

    def __init__(self, respuesta: str = "", error: Exception | None = None) -> None:
        super().__init__(client=object())
        self.respuesta = respuesta
        self.error = error
        self.prompts: list[str] = []

    def _invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if self.error is not None:
            raise self.error
        return self.respuesta


@pytest.fixture
def paciente() -> Patient:
    paciente = Patient.objects.create(
        identification_number="1098765432",
        first_name="Ana",
        last_name="Gomez",
        phone="3001234567",
        email="ana@example.com",
    )
    historial = ClinicalHistory.objects.create(patient=paciente)
    ClinicalHistoryEntry.objects.create(
        clinical_history=historial,
        entry_type="DIAGNOSIS",
        entry_date=date(2026, 1, 15),
        description="Carcinoma ductal estadio II",
    )
    PatientPathology.objects.create(
        patient=paciente,
        pathology=Pathology.objects.create(name="Carcinoma ductal"),
        is_primary=True,
    )
    return paciente


@pytest.fixture
def cita(paciente: Patient) -> Appointment:
    return Appointment.objects.create(
        patient=paciente,
        scheduled_at=timezone.now() + timedelta(days=3),
        reason="Dolor toracico de aparicion reciente",
    )


class TestSugerencia:
    def test_guarda_la_prioridad_sugerida(self, cita: Appointment) -> None:
        servicio = AppointmentPriorityService(GeminiFalso("URGENT"))

        assert servicio.suggest(cita) == "URGENT"
        cita.refresh_from_db()
        assert cita.priority_suggested_by_ai == "URGENT"

    def test_no_toca_priority_ni_priority_final(self, cita: Appointment) -> None:
        # DEC-02: la IA solo escribe su propio campo.
        AppointmentPriorityService(GeminiFalso("URGENT")).suggest(cita)

        cita.refresh_from_db()
        assert cita.priority is None
        assert cita.priority_final is None

    def test_si_gemini_falla_devuelve_none_sin_propagar(
        self, cita: Appointment
    ) -> None:
        """DEC-26: un fallo de IA no puede impedir agendar una cita."""
        servicio = AppointmentPriorityService(GeminiFalso(error=GeminiServiceError()))

        assert servicio.suggest(cita) is None
        cita.refresh_from_db()
        assert cita.priority_suggested_by_ai is None

    def test_una_prioridad_fuera_del_dominio_tampoco_propaga(
        self, cita: Appointment
    ) -> None:
        # GeminiResponseError hereda de GeminiServiceError: se trata igual.
        servicio = AppointmentPriorityService(GeminiFalso("MUY URGENTE"))

        assert servicio.suggest(cita) is None
        cita.refresh_from_db()
        assert cita.priority_suggested_by_ai is None

    def test_sin_api_key_la_cita_se_agenda_igual(self, cita: Appointment) -> None:
        """Un entorno sin `GEMINI_API_KEY` es un despliegue legitimo.

        `GeminiNotConfiguredError` NO hereda de `GeminiServiceError`, asi que si
        no se captura de forma explicita escapa como 503 e impide agendar
        cualquier cita. Este test fija esa regresion.
        """
        servicio = AppointmentPriorityService(
            GeminiFalso(error=GeminiNotConfiguredError())
        )

        assert servicio.suggest(cita) is None
        cita.refresh_from_db()
        assert cita.priority_suggested_by_ai is None

    def test_el_prompt_acota_el_dominio_a_los_valores_del_der(
        self, cita: Appointment
    ) -> None:
        doble = GeminiFalso("URGENT")
        AppointmentPriorityService(doble).suggest(cita)

        for valor in AppointmentPriority.values:
            assert valor in doble.prompts[0]


class TestContexto:
    def test_incluye_motivo_patologias_e_historial(self, cita: Appointment) -> None:
        contexto = AppointmentPriorityService.build_context(cita)

        assert contexto["motivo_de_consulta"] == "Dolor toracico de aparicion reciente"
        assert contexto["patologias"] == ["Carcinoma ductal"]
        assert contexto["entradas_recientes"][0]["descripcion"] == (
            "Carcinoma ductal estadio II"
        )

    def test_no_incluye_datos_identificativos(self, cita: Appointment) -> None:
        # DEC-25: privacidad en todo lo que se envia al modelo.
        import json

        enviado = json.dumps(
            AppointmentPriorityService.build_context(cita), ensure_ascii=False
        )
        for dato in ("1098765432", "3001234567", "ana@example.com", "Gomez"):
            assert dato not in enviado

    def test_funciona_sin_historial_clinico(self, paciente: Patient) -> None:
        ClinicalHistory.objects.filter(patient=paciente).delete()
        cita = Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(days=1)
        )

        contexto = AppointmentPriorityService.build_context(cita)
        assert contexto["entradas_recientes"] == []


class TestConfirmacion:
    def test_escribe_priority_final_y_priority(self, cita: Appointment) -> None:
        AppointmentPriorityService.confirm(cita, "ROUTINE_CONTROL")

        cita.refresh_from_db()
        assert cita.priority_final == "ROUTINE_CONTROL"
        assert cita.priority == "ROUTINE_CONTROL"

    def test_conserva_la_sugerencia_original(self, cita: Appointment) -> None:
        AppointmentPriorityService(GeminiFalso("URGENT")).suggest(cita)
        AppointmentPriorityService.confirm(cita, "ROUTINE_CONTROL")

        cita.refresh_from_db()
        # La trazabilidad de lo que sugirio la IA no se pierde al discrepar.
        assert cita.priority_suggested_by_ai == "URGENT"


class TestEstadoDeValidacion:
    def test_sin_sugerencia_no_hay_nada_pendiente(self, cita: Appointment) -> None:
        assert AppointmentPriorityService.is_pending_validation(cita) is False

    def test_con_sugerencia_sin_confirmar_esta_pendiente(
        self, cita: Appointment
    ) -> None:
        AppointmentPriorityService(GeminiFalso("URGENT")).suggest(cita)
        assert AppointmentPriorityService.is_pending_validation(cita) is True

    def test_tras_confirmar_deja_de_estarlo(self, cita: Appointment) -> None:
        AppointmentPriorityService(GeminiFalso("URGENT")).suggest(cita)
        AppointmentPriorityService.confirm(cita, "URGENT")
        assert AppointmentPriorityService.is_pending_validation(cita) is False


class TestErroresDeGemini:
    def test_la_jerarquia_permite_capturar_ambos(self) -> None:
        assert issubclass(GeminiResponseError, GeminiServiceError)
