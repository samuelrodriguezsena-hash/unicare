"""Tests de la agenda (FASE 10).

La IA se sustituye por un doble: ninguna llamada real. Requiere PostgreSQL.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.appointments.choices import AppointmentStatus
from apps.appointments.models import Appointment, AppointmentReminder
from apps.appointments.services import appointments as appointments_module
from apps.appointments.services.calendar import CalendarService
from apps.core.exceptions import GeminiServiceError
from apps.core.models import AuditLog, User
from apps.people.models import ClinicalHistory, ClinicalHistoryEntry, Patient
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

CITAS = "/api/v1/appointments/"
CALENDARIO = "/api/v1/appointments/calendar/"


class PrioridadFalsa:
    """Doble de `AppointmentPriorityService` para el alta de citas."""

    def __init__(self, prioridad: str | None = None, error: Exception | None = None):
        self.prioridad = prioridad
        self.error = error
        self.contextos: list[dict] = []

    def suggest(self, cita: Appointment) -> str | None:
        from apps.appointments.services.priority import AppointmentPriorityService

        self.contextos.append(AppointmentPriorityService.build_context(cita))
        if self.error is not None:
            # Reproduce el comportamiento real: la IA falla y la cita sigue.
            return None
        if self.prioridad is None:
            return None
        cita.priority_suggested_by_ai = self.prioridad
        cita.save(update_fields=["priority_suggested_by_ai", "updated_at"])
        return self.prioridad


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
        identification_number="1098765432", first_name="Ana", last_name="Gomez"
    )
    historial = ClinicalHistory.objects.create(patient=paciente)
    ClinicalHistoryEntry.objects.create(
        clinical_history=historial,
        entry_type="DIAGNOSIS",
        entry_date=date(2026, 1, 15),
        description="Carcinoma ductal estadio II",
    )
    return paciente


@pytest.fixture
def sin_ia(monkeypatch: pytest.MonkeyPatch) -> PrioridadFalsa:
    """Por defecto la IA no sugiere nada, para no ensuciar los tests."""
    doble = PrioridadFalsa()
    monkeypatch.setattr(
        appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
    )
    return doble


@pytest.fixture
def datos_cita(paciente: Patient) -> dict:
    return {
        "patient": paciente.pk,
        "scheduled_at": (timezone.now() + timedelta(days=3)).isoformat(),
        "reason": "Control post-quimioterapia",
    }


@pytest.fixture
def cita(client: APIClient, datos_cita: dict, sin_ia: PrioridadFalsa) -> dict:
    return client.post(CITAS, datos_cita, format="json").json()


class TestAgendar:
    def test_crea_una_cita(
        self, client: APIClient, datos_cita: dict, sin_ia: PrioridadFalsa
    ) -> None:
        respuesta = client.post(CITAS, datos_cita, format="json")
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["patient_name"] == "Ana Gomez"
        assert cuerpo["reason"] == "Control post-quimioterapia"

    def test_el_estado_por_defecto_es_agendada(
        self, client: APIClient, cita: dict
    ) -> None:
        # El DER lo declara nullable; el default se aplica en la API.
        assert cita["status"] == AppointmentStatus.SCHEDULED

    def test_rechaza_un_estado_fuera_del_enum(
        self, client: APIClient, datos_cita: dict, sin_ia: PrioridadFalsa
    ) -> None:
        datos_cita["status"] = "INVENTADO"
        assert client.post(CITAS, datos_cita, format="json").status_code == 400

    def test_el_paciente_es_obligatorio(
        self, client: APIClient, sin_ia: PrioridadFalsa
    ) -> None:
        respuesta = client.post(
            CITAS, {"scheduled_at": timezone.now().isoformat()}, format="json"
        )
        assert respuesta.status_code == 400
        assert "patient" in respuesta.json()

    def test_reprograma_una_cita(self, client: APIClient, cita: dict) -> None:
        nueva = (timezone.now() + timedelta(days=10)).isoformat()
        respuesta = client.patch(
            f"{CITAS}{cita['appointment_id']}/", {"scheduled_at": nueva}, format="json"
        )
        assert respuesta.status_code == 200

    def test_no_expone_borrado(self, client: APIClient, cita: dict) -> None:
        assert client.delete(f"{CITAS}{cita['appointment_id']}/").status_code == 405

    def test_filtros(self, client: APIClient, cita: dict, paciente: Patient) -> None:
        assert client.get(CITAS, {"patient": paciente.pk}).json()["count"] == 1
        assert client.get(CITAS, {"status": "SCHEDULED"}).json()["count"] == 1
        assert client.get(CITAS, {"status": "CANCELLED"}).json()["count"] == 0


class TestCancelar:
    def test_cancela_sin_borrar(self, client: APIClient, cita: dict) -> None:
        respuesta = client.post(f"{CITAS}{cita['appointment_id']}/cancel/")
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == AppointmentStatus.CANCELLED
        assert Appointment.objects.filter(pk=cita["appointment_id"]).exists()

    def test_es_idempotente(self, client: APIClient, cita: dict) -> None:
        url = f"{CITAS}{cita['appointment_id']}/cancel/"
        client.post(url)
        assert client.post(url).status_code == 200


class TestPriorizacionConIa:
    def test_la_ia_solo_escribe_su_propio_campo(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # DEC-02: la IA nunca escribe `priority` ni `priority_final`.
        doble = PrioridadFalsa("URGENT")
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        cuerpo = client.post(CITAS, datos_cita, format="json").json()

        assert cuerpo["priority_suggested_by_ai"] == "URGENT"
        assert cuerpo["priority"] is None
        assert cuerpo["priority_final"] is None

    def test_la_sugerencia_nace_pendiente_de_validacion(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = PrioridadFalsa("URGENT")
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        cuerpo = client.post(CITAS, datos_cita, format="json").json()

        assert cuerpo["ai_priority_pending_validation"] is True

    def test_si_la_ia_falla_la_cita_se_agenda_igual(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Agendar es la operacion clinica; priorizar es apoyo (DEC-26)."""
        doble = PrioridadFalsa(error=GeminiServiceError())
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        respuesta = client.post(CITAS, datos_cita, format="json")

        assert respuesta.status_code == 201
        assert respuesta.json()["priority_suggested_by_ai"] is None
        assert Appointment.objects.count() == 1

    def test_el_contexto_incluye_motivo_e_historial(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = PrioridadFalsa("URGENT")
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        client.post(CITAS, datos_cita, format="json")

        contexto = doble.contextos[0]
        assert contexto["motivo_de_consulta"] == "Control post-quimioterapia"
        assert contexto["entradas_recientes"][0]["tipo"] == "DIAGNOSIS"

    def test_el_cliente_no_puede_falsificar_la_sugerencia(
        self, client: APIClient, datos_cita: dict, sin_ia: PrioridadFalsa
    ) -> None:
        datos_cita["priority_suggested_by_ai"] = "URGENT"
        datos_cita["priority_final"] = "URGENT"
        cuerpo = client.post(CITAS, datos_cita, format="json").json()

        assert cuerpo["priority_suggested_by_ai"] is None
        assert cuerpo["priority_final"] is None


class TestConfirmacionProfesional:
    URL = CITAS + "{}/priority/"

    def test_registra_la_prioridad_decidida(
        self, client: APIClient, cita: dict
    ) -> None:
        respuesta = client.post(
            self.URL.format(cita["appointment_id"]),
            {"priority_final": "ROUTINE_CONTROL"},
            format="json",
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["priority_final"] == "ROUTINE_CONTROL"
        # Tambien el enum operativo con el que trabaja la agenda.
        assert cuerpo["priority"] == "ROUTINE_CONTROL"

    def test_al_confirmar_deja_de_estar_pendiente(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = PrioridadFalsa("URGENT")
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        cita = client.post(CITAS, datos_cita, format="json").json()

        cuerpo = client.post(
            self.URL.format(cita["appointment_id"]),
            {"priority_final": "URGENT"},
            format="json",
        ).json()

        assert cuerpo["ai_priority_pending_validation"] is False
        # La sugerencia original se conserva: queda la trazabilidad.
        assert cuerpo["priority_suggested_by_ai"] == "URGENT"

    def test_el_profesional_puede_discrepar_de_la_ia(
        self, client: APIClient, datos_cita: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        doble = PrioridadFalsa("URGENT")
        monkeypatch.setattr(
            appointments_module, "AppointmentPriorityService", lambda *a, **k: doble
        )
        cita = client.post(CITAS, datos_cita, format="json").json()

        cuerpo = client.post(
            self.URL.format(cita["appointment_id"]),
            {"priority_final": "ROUTINE_CONTROL"},
            format="json",
        ).json()

        assert cuerpo["priority_suggested_by_ai"] == "URGENT"
        assert cuerpo["priority_final"] == "ROUTINE_CONTROL"

    def test_rechaza_una_prioridad_fuera_del_enum(
        self, client: APIClient, cita: dict
    ) -> None:
        respuesta = client.post(
            self.URL.format(cita["appointment_id"]),
            {"priority_final": "MUY URGENTE"},
            format="json",
        )
        assert respuesta.status_code == 400


class TestCalendario:
    @pytest.fixture
    def citas(self, client: APIClient, paciente: Patient, sin_ia) -> list[dict]:
        base = timezone.now().replace(hour=10, minute=0, second=0, microsecond=0)
        momentos = [base, base + timedelta(days=1), base + timedelta(days=40)]
        return [
            client.post(
                CITAS,
                {"patient": paciente.pk, "scheduled_at": m.isoformat()},
                format="json",
            ).json()
            for m in momentos
        ]

    def test_vista_de_dia(self, client: APIClient, citas: list[dict]) -> None:
        cuerpo = client.get(CALENDARIO, {"view": "day"}).json()
        assert cuerpo["view"] == "day"
        assert len(cuerpo["events"]) == 1

    def test_vista_de_semana(self, client: APIClient, citas: list[dict]) -> None:
        cuerpo = client.get(CALENDARIO, {"view": "week"}).json()
        # La de manana puede caer en la semana siguiente si hoy es domingo.
        assert 1 <= len(cuerpo["events"]) <= 2

    def test_vista_de_mes(self, client: APIClient, citas: list[dict]) -> None:
        cuerpo = client.get(CALENDARIO, {"view": "month"}).json()
        assert len(cuerpo["events"]) >= 1
        # La cita a 40 dias queda fuera del mes en curso.
        assert len(cuerpo["events"]) <= 2

    def test_el_evento_tiene_el_formato_de_las_librerias_de_calendario(
        self, client: APIClient, citas: list[dict]
    ) -> None:
        evento = client.get(CALENDARIO, {"view": "day"}).json()["events"][0]
        assert set(evento) == {"id", "title", "start", "extendedProps"}
        assert evento["title"] == "Ana Gomez"
        assert evento["extendedProps"]["status"] == "SCHEDULED"

    def test_el_evento_no_tiene_fin_porque_el_der_no_define_duracion(
        self, client: APIClient, citas: list[dict]
    ) -> None:
        # Inventar una duracion seria anadir informacion clinica inexistente.
        evento = client.get(CALENDARIO, {"view": "day"}).json()["events"][0]
        assert "end" not in evento
        assert not hasattr(Appointment, "end_at")

    def test_acepta_una_fecha_concreta(
        self, client: APIClient, citas: list[dict]
    ) -> None:
        manana = (timezone.localdate() + timedelta(days=1)).isoformat()
        cuerpo = client.get(CALENDARIO, {"view": "day", "date": manana}).json()
        assert len(cuerpo["events"]) == 1

    def test_filtra_por_paciente(
        self, client: APIClient, citas: list[dict], paciente: Patient
    ) -> None:
        cuerpo = client.get(
            CALENDARIO, {"view": "month", "patient": paciente.pk}
        ).json()
        assert len(cuerpo["events"]) >= 1

        vacio = client.get(CALENDARIO, {"view": "month", "patient": 999999}).json()
        assert vacio["events"] == []

    def test_rechaza_una_vista_invalida(self, client: APIClient) -> None:
        assert client.get(CALENDARIO, {"view": "trimestre"}).status_code == 400

    def test_el_calendario_no_altera_el_modelo(self) -> None:
        """Es una representacion alternativa, no una estructura nueva."""
        columnas = {f.column for f in Appointment._meta.concrete_fields}
        assert "title" not in columnas
        assert "start" not in columnas


class TestRangosDelCalendario:
    """Unitarios del calculo de rangos."""

    def test_dia(self) -> None:
        inicio, fin = CalendarService.range_for("day", date(2026, 3, 15))
        assert (inicio.date(), fin.date()) == (date(2026, 3, 15), date(2026, 3, 16))

    def test_semana_empieza_en_lunes(self) -> None:
        # 2026-03-15 es domingo.
        inicio, fin = CalendarService.range_for("week", date(2026, 3, 15))
        assert inicio.date() == date(2026, 3, 9)
        assert fin.date() == date(2026, 3, 16)

    def test_mes(self) -> None:
        inicio, fin = CalendarService.range_for("month", date(2026, 3, 15))
        assert inicio.date() == date(2026, 3, 1)
        assert fin.date() == date(2026, 4, 1)

    def test_febrero_bisiesto(self) -> None:
        inicio, fin = CalendarService.range_for("month", date(2024, 2, 10))
        assert inicio.date() == date(2024, 2, 1)
        assert fin.date() == date(2024, 3, 1)

    def test_los_rangos_llevan_zona_horaria(self) -> None:
        inicio, _ = CalendarService.range_for("day", date(2026, 3, 15))
        assert timezone.is_aware(inicio)

    def test_una_vista_desconocida_es_error_de_dominio(self) -> None:
        from apps.appointments.services.calendar import InvalidCalendarViewError

        with pytest.raises(InvalidCalendarViewError):
            CalendarService.range_for("trimestre", date(2026, 3, 15))


class TestRecordatorios:
    def test_lista_los_recordatorios_de_la_cita(
        self, client: APIClient, cita: dict
    ) -> None:
        AppointmentReminder.objects.create(
            appointment_id=cita["appointment_id"],
            scheduled_at=timezone.now(),
            channel="EMAIL",
            status="PENDING",
        )
        respuesta = client.get(f"{CITAS}{cita['appointment_id']}/reminders/")

        assert respuesta.status_code == 200
        assert respuesta.json()[0]["channel"] == "EMAIL"

    def test_no_se_programan_para_un_paciente_sin_contacto(
        self, client: APIClient, cita: dict
    ) -> None:
        """El paciente de este fixture no tiene email ni telefono.

        La programacion completa se prueba en `tests/test_reminders.py`, que
        ademas captura los callbacks de `on_commit`.
        """
        assert client.get(f"{CITAS}{cita['appointment_id']}/reminders/").json() == []

    def test_no_se_pueden_crear_por_api(self, client: APIClient, cita: dict) -> None:
        # Los programa el sistema, no el cliente.
        respuesta = client.post(
            f"{CITAS}{cita['appointment_id']}/reminders/", {}, format="json"
        )
        assert respuesta.status_code == 405


class TestSeguridadYAuditoria:
    @pytest.mark.parametrize("metodo", ["get", "post"])
    def test_un_anonimo_no_puede_operar(self, metodo: str) -> None:
        assert getattr(APIClient(), metodo)(CITAS).status_code == 401

    def test_el_calendario_tambien_exige_autenticacion(self) -> None:
        assert APIClient().get(CALENDARIO).status_code == 401

    def test_el_alta_queda_auditada(
        self, client: APIClient, clinico: User, cita: dict
    ) -> None:
        registro = AuditLog.objects.get(
            entity_type="appointment",
            entity_id=cita["appointment_id"],
            action="CREATE",
        )
        assert registro.user_id == clinico.pk

    def test_la_confirmacion_de_prioridad_queda_auditada(
        self, client: APIClient, cita: dict
    ) -> None:
        client.post(
            f"{CITAS}{cita['appointment_id']}/priority/",
            {"priority_final": "URGENT"},
            format="json",
        )
        registro = AuditLog.objects.filter(
            entity_type="appointment",
            entity_id=cita["appointment_id"],
            action="UPDATE",
        ).latest("audit_id")
        assert registro.new_values["priority_final"] == "URGENT"


class TestRendimiento:
    def test_el_listado_no_incurre_en_n_mas_1(
        self,
        client: APIClient,
        paciente: Patient,
        sin_ia: PrioridadFalsa,
        django_assert_max_num_queries: Any,
    ) -> None:
        for i in range(8):
            client.post(
                CITAS,
                {
                    "patient": paciente.pk,
                    "scheduled_at": (
                        timezone.now() + timedelta(days=i + 1)
                    ).isoformat(),
                },
                format="json",
            )

        # Conteo + citas + prefetch de recordatorios.
        with django_assert_max_num_queries(4):
            client.get(CITAS)

    def test_el_calendario_no_incurre_en_n_mas_1(
        self,
        client: APIClient,
        paciente: Patient,
        sin_ia: PrioridadFalsa,
        django_assert_max_num_queries: Any,
    ) -> None:
        base = datetime.combine(timezone.localdate(), datetime.min.time())
        base = timezone.make_aware(base, timezone.get_current_timezone())
        for i in range(8):
            client.post(
                CITAS,
                {
                    "patient": paciente.pk,
                    "scheduled_at": (base + timedelta(hours=i + 1)).isoformat(),
                },
                format="json",
            )

        # Una sola consulta: el paciente viene por select_related.
        with django_assert_max_num_queries(1):
            client.get(CALENDARIO, {"view": "day"})


class TestDescripcionDeLaApi:
    """`OPTIONS` debe anunciar solo los campos escribibles."""

    def test_options_del_listado(self, client: APIClient) -> None:
        campos = client.options(CITAS).json()["actions"]["POST"]
        assert "patient" in campos
        assert "scheduled_at" in campos
        # DEC-02: estos dos no los escribe el cliente.
        assert "priority_suggested_by_ai" not in campos
        assert "priority_final" not in campos

    def test_options_del_detalle(self, client: APIClient, cita: dict) -> None:
        respuesta = client.options(f"{CITAS}{cita['appointment_id']}/")
        assert respuesta.status_code == 200


class TestDetalle:
    def test_devuelve_la_cita(self, client: APIClient, cita: dict) -> None:
        respuesta = client.get(f"{CITAS}{cita['appointment_id']}/")

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["appointment_id"] == cita["appointment_id"]
        assert cuerpo["patient_name"] == "Ana Gomez"
        assert cuerpo["reminders"] == []

    def test_devuelve_404_si_no_existe(self, client: APIClient) -> None:
        assert client.get(f"{CITAS}999999/").status_code == 404
