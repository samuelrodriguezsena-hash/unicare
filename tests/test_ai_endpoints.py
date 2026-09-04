"""Tests de los endpoints asistidos por IA (FASE 9).

El SDK de Gemini se sustituye por un doble en `GeminiService`. Ninguna llamada
real. Requiere PostgreSQL porque se verifica lo que queda persistido.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from apps.core.exceptions import GeminiServiceError
from apps.core.models import User
from apps.core.services.gemini import GeminiService
from apps.medications.services import suggestion as suggestion_module
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Note,
    Pathology,
    Patient,
    PatientPathology,
)
from apps.people.services import clinical_summary as summary_module
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

SUGERENCIAS = "/api/v1/treatment-suggestions/"


class GeminiFalso(GeminiService):
    """Doble que registra el contexto recibido y devuelve lo que se le diga."""

    def __init__(self, respuesta: Any = None, error: Exception | None = None) -> None:
        super().__init__(client=object())
        self.respuesta = respuesta
        self.error = error
        self.contextos: list[dict] = []

    def _invoke(self, prompt: str) -> str:
        if self.error is not None:
            raise self.error
        return self.respuesta

    def generate_clinical_summary(self, historial: dict) -> str:
        self.contextos.append(historial)
        return super().generate_clinical_summary(historial)

    def suggest_treatment(self, contexto: dict) -> dict:
        self.contextos.append(contexto)
        return super().suggest_treatment(contexto)


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def client(clinico: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=clinico)
    return api


@pytest.fixture
def paciente() -> Patient:
    paciente = Patient.objects.create(
        identification_number="1098765432",
        first_name="Ana",
        last_name="Gomez",
        date_of_birth=date(1980, 5, 14),
        phone="3001234567",
        email="ana@example.com",
        address="Calle Falsa 123",
    )
    historial = ClinicalHistory.objects.create(patient=paciente)
    ClinicalHistoryEntry.objects.create(
        clinical_history=historial,
        entry_type="DIAGNOSIS",
        entry_date=date(2026, 1, 15),
        description="Carcinoma ductal infiltrante estadio II",
    )
    Note.objects.create(clinical_history=historial, text="Tolera bien el esquema")
    PatientPathology.objects.create(
        patient=paciente,
        pathology=Pathology.objects.create(name="Carcinoma ductal"),
        is_primary=True,
        diagnosis_date=date(2026, 1, 15),
    )
    return paciente


def instalar(monkeypatch: pytest.MonkeyPatch, modulo, doble: GeminiFalso) -> None:
    """Sustituye `GeminiService` en el modulo del servicio de aplicacion."""
    monkeypatch.setattr(modulo, "GeminiService", lambda *a, **k: doble)


class TestResumenClinico:
    URL = "/api/v1/patients/{}/ai-summary/"

    def test_genera_y_devuelve_el_resumen(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instalar(monkeypatch, summary_module, GeminiFalso("Paciente de 46 anos..."))

        respuesta = client.post(self.URL.format(paciente.pk))

        assert respuesta.status_code == 200
        assert respuesta.json()["summary"] == "Paciente de 46 anos..."

    def test_lo_persiste_en_el_historial(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instalar(monkeypatch, summary_module, GeminiFalso("Resumen generado"))
        client.post(self.URL.format(paciente.pk))

        historial = ClinicalHistory.objects.get(patient=paciente)
        assert historial.last_ai_summary == "Resumen generado"
        assert historial.last_ai_summary_at is not None

    def test_la_respuesta_va_etiquetada_como_ia(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instalar(monkeypatch, summary_module, GeminiFalso("Resumen"))
        cuerpo = client.post(self.URL.format(paciente.pk)).json()

        assert cuerpo["label"] == settings.AI_SUGGESTION_LABEL
        assert cuerpo["disclaimer"] == settings.AI_SUGGESTION_DISCLAIMER
        assert cuerpo["status"] == "PENDIENTE_DE_VALIDACION"

    def test_el_contexto_enviado_es_el_historial_estructurado(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = GeminiFalso("Resumen")
        instalar(monkeypatch, summary_module, doble)
        client.post(self.URL.format(paciente.pk))

        contexto = doble.contextos[0]
        assert contexto["edad"] == 46
        assert contexto["patologias"][0]["nombre"] == "Carcinoma ductal"
        assert contexto["entradas"][0]["tipo"] == "DIAGNOSIS"
        assert contexto["notas"] == ["Tolera bien el esquema"]

    def test_no_se_envian_datos_de_contacto_ni_identificacion(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Privacidad: el modelo no necesita identificar al paciente."""
        doble = GeminiFalso("Resumen")
        instalar(monkeypatch, summary_module, doble)
        client.post(self.URL.format(paciente.pk))

        enviado = json.dumps(doble.contextos[0], ensure_ascii=False)
        for dato in ("1098765432", "3001234567", "ana@example.com", "Calle Falsa"):
            assert dato not in enviado
        assert "Gomez" not in enviado

    def test_si_gemini_falla_devuelve_502_y_no_persiste(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        instalar(monkeypatch, summary_module, GeminiFalso(error=GeminiServiceError()))

        respuesta = client.post(self.URL.format(paciente.pk))

        assert respuesta.status_code == 502
        assert ClinicalHistory.objects.get(patient=paciente).last_ai_summary is None

    def test_devuelve_404_si_el_paciente_no_existe(self, client: APIClient) -> None:
        assert client.post(self.URL.format(999999)).status_code == 404

    def test_un_anonimo_no_puede_generarlo(self, paciente: Patient) -> None:
        assert APIClient().post(self.URL.format(paciente.pk)).status_code == 401


class TestSugerenciaDeTratamiento:
    SALIDA = json.dumps(
        {
            "familias_farmacologicas": ["Antraciclinas"],
            "principios_activos": ["Doxorrubicina"],
        }
    )

    @pytest.fixture
    def asociacion(self, paciente: Patient) -> PatientPathology:
        return paciente.pathologies.first()

    def test_devuelve_familias_y_principios_activos(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        instalar(monkeypatch, suggestion_module, GeminiFalso(self.SALIDA))

        respuesta = client.post(
            SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json"
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["familias_farmacologicas"] == ["Antraciclinas"]
        assert cuerpo["principios_activos"] == ["Doxorrubicina"]
        assert cuerpo["pathology_name"] == "Carcinoma ductal"

    def test_va_etiquetada_como_sugerencia_de_ia(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        instalar(monkeypatch, suggestion_module, GeminiFalso(self.SALIDA))
        cuerpo = client.post(
            SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json"
        ).json()

        assert cuerpo["label"] == "SUGERENCIA GENERADA POR IA"
        assert "requiere validacion" in cuerpo["disclaimer"]
        assert "No constituye una prescripcion" in cuerpo["disclaimer"]
        assert cuerpo["status"] == "PENDIENTE_DE_VALIDACION"

    def test_no_persiste_nada(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """C-06 / DEC-07: el DER no define donde guardarla."""
        from apps.medications.models import TreatmentPlan, TreatmentPlanMedication

        instalar(monkeypatch, suggestion_module, GeminiFalso(self.SALIDA))
        cuerpo = client.post(
            SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json"
        ).json()

        assert cuerpo["persisted"] is False
        assert TreatmentPlan.objects.count() == 0
        assert TreatmentPlanMedication.objects.count() == 0

    def test_parte_de_una_patologia_del_historial(self, client: APIClient) -> None:
        # No se aceptan nombres sueltos: la patologia debe estar registrada.
        respuesta = client.post(
            SUGERENCIAS, {"patient_pathology": 999999}, format="json"
        )
        assert respuesta.status_code == 400

    def test_el_contexto_incluye_la_patologia_y_el_historial(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        doble = GeminiFalso(self.SALIDA)
        instalar(monkeypatch, suggestion_module, doble)
        client.post(SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json")

        contexto = doble.contextos[0]
        assert contexto["patologia"] == "Carcinoma ductal"
        assert contexto["es_patologia_principal"] is True
        assert contexto["entradas_recientes"][0]["tipo"] == "DIAGNOSIS"

    def test_no_se_envian_datos_identificativos(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        doble = GeminiFalso(self.SALIDA)
        instalar(monkeypatch, suggestion_module, doble)
        client.post(SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json")

        enviado = json.dumps(doble.contextos[0], ensure_ascii=False)
        assert "1098765432" not in enviado
        assert "ana@example.com" not in enviado

    def test_una_respuesta_invalida_del_modelo_es_502(
        self,
        client: APIClient,
        asociacion: PatientPathology,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        instalar(
            monkeypatch, suggestion_module, GeminiFalso("Le recomiendo doxorrubicina")
        )
        respuesta = client.post(
            SUGERENCIAS, {"patient_pathology": asociacion.pk}, format="json"
        )

        assert respuesta.status_code == 502
        assert respuesta.json()["code"] == "gemini_response_error"

    def test_un_anonimo_no_puede_pedirla(self, asociacion: PatientPathology) -> None:
        assert APIClient().post(SUGERENCIAS).status_code == 401


class TestSinConfiguracion:
    def test_devuelve_503_si_falta_la_api_key(
        self, client: APIClient, paciente: Patient
    ) -> None:
        # GEMINI_API_KEY esta vacia en el entorno de tests.
        respuesta = client.post(f"/api/v1/patients/{paciente.pk}/ai-summary/")

        assert respuesta.status_code == 503
        assert respuesta.json()["code"] == "gemini_not_configured"


class TestAislamientoDelSdk:
    def test_ninguna_vista_ni_serializer_importa_el_sdk(self) -> None:
        """El SDK solo puede aparecer en `apps/core/services/gemini.py`."""
        from pathlib import Path

        raiz = Path("apps")
        permitido = raiz / "core" / "services" / "gemini.py"
        infractores = [
            str(fichero)
            for fichero in raiz.rglob("*.py")
            if fichero != permitido and "google" in fichero.read_text(encoding="utf-8")
        ]
        assert infractores == []


class TestContextoSinFechaDeNacimiento:
    def test_la_edad_va_nula_si_no_consta(
        self, client: APIClient, paciente: Patient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        paciente.date_of_birth = None
        paciente.save(update_fields=["date_of_birth"])
        doble = GeminiFalso("Resumen")
        instalar(monkeypatch, summary_module, doble)

        client.post(f"/api/v1/patients/{paciente.pk}/ai-summary/")

        # El prompt prohibe suponer datos: si no consta, se envia nulo.
        assert doble.contextos[0]["edad"] is None
