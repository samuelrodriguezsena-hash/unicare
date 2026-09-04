"""Tests del modelo `User` y su manager (FASE 15).

Cubren dos cosas que nada mas ejercitaba y que si importan:

  * `createsuperuser`, que la documentacion de deployment manda ejecutar;
  * la representacion en texto de todas las entidades, que es lo que aparece
    en mensajes de error y trazas.

Requiere PostgreSQL.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.appointments.models import Appointment, AppointmentReminder
from apps.core.choices import AuditAction
from apps.core.models import AuditLog, User
from apps.massive_load.models import ImportBatch, ImportBatchRow
from apps.medications.models import TreatmentPlan, TreatmentPlanMedication
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Note,
    Pathology,
    Patient,
    PatientPathology,
)
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db


class TestManagerDeUsuarios:
    def test_crea_un_usuario(self) -> None:
        usuario = User.objects.create_user(
            username="dra.rojas", email="rojas@example.com", password="x" * 14
        )
        assert usuario.pk is not None
        assert usuario.check_password("x" * 14)

    def test_el_username_es_obligatorio(self) -> None:
        with pytest.raises(ValueError, match="username"):
            User.objects.create_user(username="")

    def test_sin_contrasena_queda_inutilizable(self) -> None:
        """Es como se crea el usuario tecnico `system` (C-04)."""
        usuario = User.objects.create_user(username="robot")
        assert not usuario.has_usable_password()

    def test_normaliza_el_dominio_del_email(self) -> None:
        usuario = User.objects.create_user(
            username="dr.silva", email="silva@EXAMPLE.COM", password="y" * 14
        )
        assert usuario.email == "silva@example.com"

    def test_sin_email_queda_nulo(self) -> None:
        # El DER declara `email` nullable.
        assert User.objects.create_user(username="sin.email").email is None

    def test_createsuperuser_funciona(self) -> None:
        """La documentacion de deployment manda ejecutarlo.

        Sin `PermissionsMixin` no existen niveles de privilegio (C-02/C-03), asi
        que `create_superuser` es un alias de `create_user`. Lo importante es
        que el comando no falle en un despliegue.
        """
        usuario = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="z" * 14
        )
        assert usuario.pk is not None
        assert usuario.is_active

    def test_el_comando_de_gestion_no_revienta(self) -> None:
        """`manage.py createsuperuser` con el modelo USER del DER.

        Solo pide `username`: `REQUIRED_FIELDS` esta vacio porque el DER
        declara `email` nullable. La documentacion de deployment lo refleja.
        """
        from io import StringIO

        from django.core.management import call_command

        call_command(
            "createsuperuser",
            username="desde.comando",
            interactive=False,
            stdout=StringIO(),
        )
        assert User.objects.filter(username="desde.comando").exists()


class TestRepresentacionEnTexto:
    """`__str__` aparece en mensajes de error, trazas y `repr()`.

    Uno roto convierte un fallo diagnosticable en un `AttributeError` opaco.
    """

    def test_usuario(self) -> None:
        usuario = User.objects.create_user(username="dra.rojas")
        assert str(usuario) == "dra.rojas"

    def test_usuario_sin_username(self) -> None:
        # El DER declara `username` nullable.
        usuario = User.objects.create_user(username="temporal")
        usuario.username = None
        assert str(usuario) == f"user:{usuario.pk}"

    def test_paciente(self) -> None:
        paciente = Patient.objects.create(first_name="Ana", last_name="Gomez")
        assert str(paciente) == "Ana Gomez"

    def test_patologia(self) -> None:
        assert str(Pathology.objects.create(name="Melanoma")) == "Melanoma"

    def test_resto_de_entidades(self) -> None:
        paciente = Patient.objects.create(
            identification_number="1000000001", first_name="Ana", last_name="Gomez"
        )
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        historial = ClinicalHistory.objects.create(patient=paciente)
        lote = ImportBatch.objects.create(
            source_file_name="carga.csv", source_file_type=".csv"
        )
        cita = Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(days=1)
        )
        plan = TreatmentPlan.objects.create(
            patient=paciente, name="Plan A", start_date=date.today()
        )

        entidades = [
            historial,
            ClinicalHistoryEntry.objects.create(
                clinical_history=historial,
                entry_date=date.today(),
                description="Control",
            ),
            Note.objects.create(clinical_history=historial, text="Nota"),
            PatientPathology.objects.create(patient=paciente, pathology=patologia),
            plan,
            TreatmentPlanMedication.objects.create(
                treatment_plan=plan, external_medication_id="Atorvastatina"
            ),
            cita,
            AppointmentReminder.objects.create(
                appointment=cita, scheduled_at=timezone.now()
            ),
            lote,
            ImportBatchRow.objects.create(import_batch=lote, row_number=1),
            AuditLog.objects.create(
                user=User.objects.create_user(username="auditor"),
                entity_type="patient",
                entity_id=paciente.pk,
                action=AuditAction.CREATE,
            ),
        ]

        for entidad in entidades:
            texto = str(entidad)
            assert texto, f"{type(entidad).__name__} devuelve una cadena vacia"
            assert "object at 0x" not in texto

    def test_el_medicamento_cae_al_id_externo_sin_snapshot(self) -> None:
        paciente = Patient.objects.create(first_name="Ana", last_name="Gomez")
        plan = TreatmentPlan.objects.create(
            patient=paciente, name="Plan A", start_date=date.today()
        )
        medicamento = TreatmentPlanMedication.objects.create(
            treatment_plan=plan, external_medication_id="Atorvastatina"
        )
        assert str(medicamento) == "Atorvastatina"


class TestTareaDeDiagnostico:
    def test_debug_task_responde(self) -> None:
        """Sirve para comprobar que el worker esta vivo."""
        from config.celery import debug_task

        assert debug_task().startswith("ok:")
