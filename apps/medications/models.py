"""Modelos de `medications`: planes de tratamiento.

Entidades del DER implementadas aqui:

    TREATMENT_PLAN, TREATMENT_PLAN_MEDICATION

IMPORTANTE: no existe ni debe existir un catalogo local de medicamentos. El DER
referencia el farmaco por `external_medication_id` (identificador de la API
externa) mas dos columnas de snapshot desnormalizado. La API de farmacos es la
unica fuente de consulta farmacologica.
"""

from __future__ import annotations

from django.db import models

from apps.core.choices import ENUM_MAX_LENGTH
from apps.core.models import Auditor
from apps.medications.choices import TreatmentPlanStatus


class TreatmentPlan(Auditor):
    """Entidad `TREATMENT_PLAN` del DER."""

    treatment_plan_id = models.BigAutoField(
        primary_key=True, db_column="treatment_plan_id"
    )
    patient = models.ForeignKey(
        "people.Patient",
        on_delete=models.PROTECT,
        db_column="patient_id",
        related_name="treatment_plans",
    )
    # A-05: el DER no marca "FK" en el margen izquierdo pero el tipo declara
    # `bigint FK`, y no lo marca NOT NULL -> FK nullable.
    pathology = models.ForeignKey(
        "people.Pathology",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        db_column="pathology_id",
        related_name="treatment_plans",
    )
    name = models.CharField(max_length=255, db_column="name")
    start_date = models.DateField(db_column="start_date")
    end_date = models.DateField(null=True, blank=True, db_column="end_date")
    status = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=TreatmentPlanStatus.choices,
        null=True,
        blank=True,
        db_column="status",
    )
    clinical_note = models.TextField(null=True, blank=True, db_column="clinical_note")

    class Meta:
        db_table = "treatment_plan"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=TreatmentPlanStatus.values)
                | models.Q(status__isnull=True),
                name="ck_treatment_plan_status",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class TreatmentPlanMedication(Auditor):
    """Entidad `TREATMENT_PLAN_MEDICATION` del DER.

    `external_medication_id` apunta a la API externa de farmacos; los dos
    campos `_snapshot` conservan lo que dicha API devolvio en el momento de
    asociar el medicamento. No hay FK a ninguna tabla local de medicamentos
    porque el DER no define ninguna.

    `validation_status` y `warning_flag` sostienen la validacion cruzada
    (comparacion de `Patologia_Comun` con la patologia del paciente). La
    discrepancia produce ADVERTENCIA, nunca bloqueo automatico.
    """

    treatment_plan_medication_id = models.BigAutoField(
        primary_key=True, db_column="treatment_plan_medication_id"
    )
    treatment_plan = models.ForeignKey(
        "medications.TreatmentPlan",
        on_delete=models.CASCADE,
        db_column="treatment_plan_id",
        related_name="medications",
    )
    external_medication_id = models.CharField(
        max_length=100, db_column="external_medication_id"
    )
    # DEC-01: el DER escribe `varchar - external snapshot`, sin longitud.
    medication_name_snapshot = models.TextField(
        null=True, blank=True, db_column="medication_name_snapshot"
    )
    medication_family_snapshot = models.TextField(
        null=True, blank=True, db_column="medication_family_snapshot"
    )
    dose = models.CharField(max_length=100, null=True, blank=True, db_column="dose")
    frequency = models.CharField(
        max_length=100, null=True, blank=True, db_column="frequency"
    )
    duration = models.CharField(
        max_length=100, null=True, blank=True, db_column="duration"
    )
    route = models.CharField(max_length=100, null=True, blank=True, db_column="route")
    instructions = models.TextField(null=True, blank=True, db_column="instructions")
    # El DER lo declara varchar(30), NO enum: por eso no lleva CheckConstraint
    # ni `choices` obligatorios. Ver MedicationValidationStatus.
    validation_status = models.CharField(
        max_length=30, null=True, blank=True, db_column="validation_status"
    )
    warning_flag = models.BooleanField(null=True, blank=True, db_column="warning_flag")

    class Meta:
        db_table = "treatment_plan_medication"

    def __str__(self) -> str:
        return self.medication_name_snapshot or self.external_medication_id
