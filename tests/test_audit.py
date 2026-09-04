"""Tests de la auditoria (FASE 5).

La documentacion normativa exige poder conocer, para cada operacion critica:
usuario responsable, entidad afectada, ID, operacion, valores anteriores,
valores nuevos, cambios realizados y fecha/hora. Aqui se comprueba que
`AUDIT_LOG` lo permite sin haber alterado su estructura del DER.

Requiere PostgreSQL: la auditoria escribe en `jsonb` y se verifica leyendo lo
que quedo realmente guardado.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from django.conf import settings
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.core.choices import AuditAction
from apps.core.context import acting_as
from apps.core.models import AuditLog, User
from apps.core.services.audit import (
    AuditService,
    SystemUserMissingError,
    diff,
    serialize_instance,
    to_jsonable,
)
from apps.people.models import (
    ClinicalHistory,
    Note,
    Pathology,
    Patient,
    PatientPathology,
)
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def paciente() -> Patient:
    return Patient.objects.create(
        identification_number="1098765432", first_name="Ana", last_name="Gomez"
    )


def auditoria_de(instancia) -> list[AuditLog]:
    return list(
        AuditLog.objects.filter(
            entity_type=instancia._meta.db_table, entity_id=instancia.pk
        ).order_by("audit_id")
    )


class TestOperacionesCriticas:
    def test_crear_un_paciente_genera_auditoria(self, paciente: Patient) -> None:
        registros = auditoria_de(paciente)
        assert len(registros) == 1
        registro = registros[0]
        assert registro.action == AuditAction.CREATE
        assert registro.entity_type == "patient"
        assert registro.entity_id == paciente.pk
        assert registro.old_values is None
        assert registro.new_values["identification_number"] == "1098765432"
        assert registro.created_at is not None

    def test_modificar_registra_solo_lo_que_cambio(self, paciente: Patient) -> None:
        paciente.last_name = "Gomez Ruiz"
        paciente.save()

        registro = auditoria_de(paciente)[-1]
        assert registro.action == AuditAction.UPDATE
        # `updated_at` cambia siempre; lo relevante es el campo de negocio.
        assert registro.old_values["last_name"] == "Gomez"
        assert registro.new_values["last_name"] == "Gomez Ruiz"
        assert "first_name" not in registro.new_values

    def test_un_save_sin_cambios_no_genera_ruido(self, paciente: Patient) -> None:
        antes = AuditLog.objects.count()
        paciente.save(update_fields=[])
        assert AuditLog.objects.count() == antes

    def test_borrar_registra_el_estado_previo(self) -> None:
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        pk = patologia.pk
        patologia.delete()

        registro = AuditLog.objects.get(
            entity_type="pathology", entity_id=pk, action=AuditAction.DELETE
        )
        assert registro.old_values["name"] == "Carcinoma ductal"
        assert registro.new_values is None

    @pytest.mark.parametrize(
        "crear",
        [
            lambda p: ClinicalHistory.objects.create(patient=p),
            lambda p: Appointment.objects.create(
                patient=p, scheduled_at=timezone.now() + timedelta(days=1)
            ),
            lambda p: PatientPathology.objects.create(
                patient=p, pathology=Pathology.objects.create(name="Melanoma")
            ),
        ],
    )
    def test_las_entidades_clinicas_tambien_se_auditan(
        self, paciente: Patient, crear
    ) -> None:
        instancia = crear(paciente)
        assert auditoria_de(instancia)

    def test_audit_log_no_se_audita_a_si_mismo(self, paciente: Patient) -> None:
        # Auditarse a si mismo seria recursion infinita.
        assert not AuditLog.objects.filter(entity_type="audit_log").exists()


class TestUsuarioResponsable:
    def test_se_atribuye_al_usuario_de_la_operacion(self, clinico: User) -> None:
        with acting_as(clinico):
            paciente = Patient.objects.create(first_name="Luis", last_name="Paz")

        assert auditoria_de(paciente)[0].user_id == clinico.pk

    def test_sin_usuario_se_atribuye_al_usuario_tecnico(
        self, paciente: Patient
    ) -> None:
        # C-04: Celery y los comandos no tienen usuario autenticado.
        system = User.objects.get(username=settings.SYSTEM_USERNAME)
        assert auditoria_de(paciente)[0].user_id == system.pk

    def test_el_usuario_tecnico_no_puede_autenticarse(self) -> None:
        system = User.objects.get(username=settings.SYSTEM_USERNAME)
        assert not system.has_usable_password()

    def test_falla_de_forma_explicita_si_falta_el_usuario_tecnico(self) -> None:
        User.objects.filter(username=settings.SYSTEM_USERNAME).delete()
        with pytest.raises(SystemUserMissingError):
            AuditService.resolve_user_id()


class TestCamposDeAuditoriaDelDer:
    def test_created_by_y_updated_by_se_rellenan_solos(self, clinico: User) -> None:
        with acting_as(clinico):
            paciente = Patient.objects.create(first_name="Eva", last_name="Nieto")

        paciente.refresh_from_db()
        assert paciente.created_by_id == clinico.pk
        assert paciente.updated_by_id == clinico.pk

    def test_updated_by_cambia_pero_created_by_no(self, clinico: User) -> None:
        with acting_as(clinico):
            paciente = Patient.objects.create(first_name="Eva", last_name="Nieto")

        otro = User.objects.create_user(username="dr.silva", password="y" * 14)
        with acting_as(otro):
            paciente.first_name = "Eva Maria"
            paciente.save()

        paciente.refresh_from_db()
        assert paciente.created_by_id == clinico.pk
        assert paciente.updated_by_id == otro.pk

    def test_las_tablas_sin_auditoria_en_el_der_no_la_reciben(
        self, paciente: Patient
    ) -> None:
        # D-02: APPOINTMENT_REMINDER no tiene created_by/updated_by.
        from apps.appointments.models import AppointmentReminder

        cita = Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(days=1)
        )
        recordatorio = AppointmentReminder.objects.create(
            appointment=cita, scheduled_at=timezone.now()
        )
        assert not hasattr(recordatorio, "created_by_id")


class TestPrivacidad:
    def test_nunca_se_audita_la_contrasena(self, clinico: User) -> None:
        registro = auditoria_de(clinico)[0]
        assert "password" not in registro.new_values
        assert "last_login" not in registro.new_values

    def test_el_serializador_omite_los_campos_sensibles(self, clinico: User) -> None:
        assert "password" not in serialize_instance(clinico)


class TestSerializacion:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            (None, None),
            (True, True),
            (7, 7),
            ("texto", "texto"),
            (date(2026, 1, 31), "2026-01-31"),
            ({"a": 1}, {"a": 1}),
            ([1, 2], [1, 2]),
            (Decimal("2.50"), "2.50"),
            (
                UUID("12345678-1234-5678-1234-567812345678"),
                "12345678-1234-5678-1234-567812345678",
            ),
        ],
    )
    def test_los_valores_se_convierten_a_json(self, valor, esperado) -> None:
        assert to_jsonable(valor) == esperado

    def test_las_claves_son_nombres_fisicos_del_der(self, paciente: Patient) -> None:
        datos = serialize_instance(paciente)
        assert "identification_number" in datos
        # FK por su columna fisica, no por el atributo Python.
        assert "created_by" in datos
        assert "created_by_id" not in datos

    def test_un_tipo_desconocido_se_guarda_como_texto(self) -> None:
        class Raro:
            def __str__(self) -> str:
                return "valor-raro"

        assert to_jsonable(Raro()) == "valor-raro"

    def test_el_diff_detecta_altas_bajas_y_cambios(self) -> None:
        assert diff({"a": 1, "b": 2}, {"a": 9, "c": 3}) == ["a", "b", "c"]
        assert diff({"a": 1}, {"a": 1}) == []


class TestResiliencia:
    def test_un_fallo_de_auditoria_no_tumba_la_operacion(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Perder una entrada de auditoria es malo; perder el dato clinico, peor."""

        def explota() -> int:
            raise RuntimeError("base caida")

        monkeypatch.setattr(AuditService, "resolve_user_id", staticmethod(explota))

        paciente = Patient.objects.create(first_name="Sara", last_name="Diaz")

        assert Patient.objects.filter(pk=paciente.pk).exists()
        assert not auditoria_de(paciente)


class TestCargaDeFixtures:
    def test_una_carga_raw_no_genera_auditoria(self, paciente: Patient) -> None:
        """`loaddata` escribe tal cual: sin signals de negocio ni auditoria."""
        from apps.core.audit import _post_save, _pre_save

        antes = AuditLog.objects.count()
        _pre_save(Patient, paciente, raw=True)
        _post_save(Patient, paciente, created=False, raw=True)
        assert AuditLog.objects.count() == antes


class TestCascadaYAuditoria:
    def test_el_borrado_en_cascada_tambien_se_audita(self, paciente: Patient) -> None:
        historial = ClinicalHistory.objects.create(patient=paciente)
        nota = Note.objects.create(clinical_history=historial, text="Control")
        nota_pk = nota.pk

        historial.delete()

        assert AuditLog.objects.filter(
            entity_type="note", entity_id=nota_pk, action=AuditAction.DELETE
        ).exists()


class TestModificacionSinCambios:
    def test_no_registra_nada_si_no_cambio_ningun_valor(
        self, paciente: Patient
    ) -> None:
        """Un `save()` que no altera nada no es una operacion auditable."""
        antes = AuditLog.objects.count()
        instantanea = serialize_instance(paciente)

        assert AuditService.log_update(paciente, instantanea) is None
        assert AuditLog.objects.count() == antes
