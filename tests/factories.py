"""Factories de `factory-boy`.

Sirven para los tests que necesitan POBLACION: los que comprueban N+1,
paginacion o filtros sobre muchos registros, donde escribir cada objeto a mano
esconde lo que el test realmente afirma.

Los tests que comprueban una regla concreta siguen construyendo sus datos de
forma explicita: ahi ver el dato exacto ES parte del test.

Todas usan `django_get_or_create` o secuencias para no chocar con las
restricciones UNIQUE del DER.
"""

from __future__ import annotations

from datetime import timedelta

import factory
from django.utils import timezone

from apps.appointments.choices import AppointmentStatus
from apps.appointments.models import Appointment, AppointmentReminder
from apps.core.models import User
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


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: f"clinico{n}")
    email = factory.LazyAttribute(lambda o: f"{o.username}@example.invalid")
    is_active = True


class PatientFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Patient

    # El DER declara `identification_number` UNIQUE.
    identification_number = factory.Sequence(lambda n: f"90000{n:05d}")
    first_name = factory.Sequence(lambda n: f"Paciente{n}")
    last_name = "Prueba"
    date_of_birth = factory.LazyFunction(
        lambda: timezone.localdate() - timedelta(days=365 * 40)
    )
    email = factory.LazyAttribute(
        lambda o: f"{o.identification_number}@example.invalid"
    )
    is_active = True


class PathologyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Pathology
        django_get_or_create = ("name",)

    name = factory.Sequence(lambda n: f"Patologia {n}")


class PatientPathologyFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PatientPathology

    patient = factory.SubFactory(PatientFactory)
    pathology = factory.SubFactory(PathologyFactory)
    is_primary = False


class ClinicalHistoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClinicalHistory
        # El DER lo declara 1:1 con PATIENT.
        django_get_or_create = ("patient",)

    patient = factory.SubFactory(PatientFactory)


class ClinicalHistoryEntryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ClinicalHistoryEntry

    clinical_history = factory.SubFactory(ClinicalHistoryFactory)
    entry_type = "OBSERVATION"
    entry_date = factory.LazyFunction(timezone.localdate)
    description = "Evolucion sin novedades."


class NoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Note

    clinical_history = factory.SubFactory(ClinicalHistoryFactory)
    text = "Nota de seguimiento."


class TreatmentPlanFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = TreatmentPlan

    patient = factory.SubFactory(PatientFactory)
    name = factory.Sequence(lambda n: f"Plan {n}")
    start_date = factory.LazyFunction(timezone.localdate)
    status = "ACTIVE"


class TreatmentPlanMedicationFactory(factory.django.DjangoModelFactory):
    """Medicamento ya asociado.

    Se salta la validacion cruzada a proposito: sirve para poblar, no para
    probar el flujo de asociacion, que tiene sus propios tests con la API
    externa mockeada.
    """

    class Meta:
        model = TreatmentPlanMedication

    treatment_plan = factory.SubFactory(TreatmentPlanFactory)
    external_medication_id = factory.Sequence(lambda n: f"Medicamento{n}")
    medication_name_snapshot = factory.SelfAttribute("external_medication_id")
    medication_family_snapshot = "Familia de prueba"


class AppointmentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Appointment

    patient = factory.SubFactory(PatientFactory)
    scheduled_at = factory.Sequence(
        lambda n: timezone.now() + timedelta(days=1, hours=n)
    )
    status = AppointmentStatus.SCHEDULED
    reason = "Control de rutina."


class AppointmentReminderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = AppointmentReminder

    appointment = factory.SubFactory(AppointmentFactory)
    channel = "EMAIL"
    scheduled_at = factory.LazyAttribute(
        lambda o: o.appointment.scheduled_at - timedelta(hours=24)
    )
    status = "PENDING"


class ImportBatchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportBatch

    source_file_name = factory.Sequence(lambda n: f"carga{n}.csv")
    source_file_type = ".csv"
    status = "PENDING"
    total_rows = 0
    success_count = 0
    failure_count = 0


class ImportBatchRowFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ImportBatchRow

    import_batch = factory.SubFactory(ImportBatchFactory)
    row_number = factory.Sequence(lambda n: n + 1)
    identification_number = factory.Sequence(lambda n: f"90000{n:05d}")
    patient_name_snapshot = "Paciente Prueba"
    pathology_name_snapshot = "Patologia de prueba"
    status = "PENDING"
