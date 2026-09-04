"""Modelos de `people`: pacientes e informacion clinica.

Entidades del DER implementadas aqui:

    PATIENT, PATHOLOGY, PATIENT_PATHOLOGY,
    CLINICAL_HISTORY, CLINICAL_HISTORY_ENTRY, NOTE

Reglas aplicadas en todo el modulo:

  * `db_table` y `db_column` reproducen los nombres fisicos del DER (DEC-09).
  * `null=True` UNICAMENTE donde el DER omite `NOT NULL`.
  * `on_delete` segun DEC-04: PROTECT en dominio, CASCADE en composicion.
  * `varchar` sin longitud -> `TextField` (DEC-01).
  * Ninguna relacion se modela como `ManyToManyField`: `PATIENT_PATHOLOGY` es
    una entidad asociativa explicita del DER, con atributos y auditoria.
"""

from __future__ import annotations

from django.db import models

from apps.core.choices import ENUM_MAX_LENGTH
from apps.core.models import Auditor
from apps.people.choices import ClinicalHistoryEntryType


class Patient(Auditor):
    """Entidad `PATIENT` del DER."""

    patient_id = models.BigAutoField(primary_key=True, db_column="patient_id")
    # A-01: el DER lo declara UNIQUE pero NO NOT NULL. Se respeta: PostgreSQL
    # admite multiples NULL en un indice unico. La obligatoriedad al crear un
    # paciente por API se impone en el serializer, no en el esquema.
    # DEC-01: `varchar` sin longitud -> TextField.
    identification_number = models.TextField(
        unique=True, null=True, blank=True, db_column="identification_number"
    )
    first_name = models.CharField(max_length=100, db_column="first_name")
    last_name = models.CharField(max_length=100, db_column="last_name")
    date_of_birth = models.DateField(null=True, blank=True, db_column="date_of_birth")
    phone = models.CharField(max_length=30, null=True, blank=True, db_column="phone")
    email = models.EmailField(max_length=255, null=True, blank=True, db_column="email")
    address = models.CharField(
        max_length=255, null=True, blank=True, db_column="address"
    )
    # A-09: la baja es logica. No se expone borrado fisico de pacientes.
    is_active = models.BooleanField(default=True, db_column="is_active")

    class Meta:
        db_table = "patient"
        # DEC-05: indices no unicos para busqueda por nombre y filtrado por
        # estado. No alteran el contrato del DER.
        indexes = [
            models.Index(fields=["last_name", "first_name"], name="ix_patient_name"),
            models.Index(fields=["is_active"], name="ix_patient_is_active"),
        ]

    def __str__(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Pathology(Auditor):
    """Entidad `PATHOLOGY` del DER."""

    pathology_id = models.BigAutoField(primary_key=True, db_column="pathology_id")
    name = models.CharField(max_length=255, unique=True, db_column="name")
    description = models.TextField(null=True, blank=True, db_column="description")

    class Meta:
        db_table = "pathology"

    def __str__(self) -> str:
        return self.name


class PatientPathology(Auditor):
    """Entidad `PATIENT_PATHOLOGY` del DER.

    Tabla asociativa explicita, con atributos propios y auditoria. El DER la
    modela como entidad, por lo que NO se sustituye por un `ManyToManyField`.
    """

    patient_pathology_id = models.BigAutoField(
        primary_key=True, db_column="patient_pathology_id"
    )
    patient = models.ForeignKey(
        "people.Patient",
        on_delete=models.PROTECT,
        db_column="patient_id",
        related_name="pathologies",
    )
    pathology = models.ForeignKey(
        "people.Pathology",
        on_delete=models.PROTECT,
        db_column="pathology_id",
        related_name="patient_links",
    )
    # El DER escribe `bool` sin NOT NULL -> nullable (A-07).
    is_primary = models.BooleanField(null=True, blank=True, db_column="is_primary")
    diagnosis_date = models.DateField(null=True, blank=True, db_column="diagnosis_date")
    notes = models.TextField(null=True, blank=True, db_column="notes")

    class Meta:
        db_table = "patient_pathology"
        constraints = [
            # Declarada explicitamente en el DER como `uq_patient_pathology`.
            models.UniqueConstraint(
                fields=["patient", "pathology"], name="uq_patient_pathology"
            ),
            # A-04: traduccion literal de la regla escrita dentro del DER,
            # "bool; max 1 primary/patient". No es una adicion al contrato.
            models.UniqueConstraint(
                fields=["patient"],
                condition=models.Q(is_primary=True),
                name="uq_patient_primary_pathology",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.patient_id}:{self.pathology_id}"


class ClinicalHistory(Auditor):
    """Entidad `CLINICAL_HISTORY` del DER.

    El DER declara `patient_id` como `bigint UNIQUE NOT NULL`, lo que fuerza
    una relacion 1:1 con `PATIENT`. `OneToOneField` produce exactamente esa
    columna con esa restriccion unica.
    """

    clinical_history_id = models.BigAutoField(
        primary_key=True, db_column="clinical_history_id"
    )
    patient = models.OneToOneField(
        "people.Patient",
        on_delete=models.PROTECT,
        db_column="patient_id",
        related_name="clinical_history",
    )
    # Cache del ultimo resumen generado por Gemini. C-06: el DER no define un
    # estado de aprobacion para el resumen, por lo que no se inventa ninguno.
    last_ai_summary = models.TextField(
        null=True, blank=True, db_column="last_ai_summary"
    )
    last_ai_summary_at = models.DateTimeField(
        null=True, blank=True, db_column="last_ai_summary_at"
    )

    class Meta:
        db_table = "clinical_history"

    def __str__(self) -> str:
        return f"historial:{self.patient_id}"


class ClinicalHistoryEntry(Auditor):
    """Entidad `CLINICAL_HISTORY_ENTRY` del DER."""

    clinical_history_entry_id = models.BigAutoField(
        primary_key=True, db_column="clinical_history_entry_id"
    )
    clinical_history = models.ForeignKey(
        "people.ClinicalHistory",
        on_delete=models.CASCADE,
        db_column="clinical_history_id",
        related_name="entries",
    )
    entry_type = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=ClinicalHistoryEntryType.choices,
        null=True,
        blank=True,
        db_column="entry_type",
    )
    entry_date = models.DateField(db_column="entry_date")
    description = models.TextField(db_column="description")

    class Meta:
        db_table = "clinical_history_entry"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(entry_type__in=ClinicalHistoryEntryType.values)
                | models.Q(entry_type__isnull=True),
                name="ck_clinical_history_entry_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.entry_type} {self.entry_date}"


class Note(Auditor):
    """Entidad `NOTE` del DER.

    Cuelga de `CLINICAL_HISTORY`, no de `PATIENT` (D-05).
    """

    note_id = models.BigAutoField(primary_key=True, db_column="note_id")
    clinical_history = models.ForeignKey(
        "people.ClinicalHistory",
        on_delete=models.CASCADE,
        db_column="clinical_history_id",
        related_name="notes",
    )
    text = models.TextField(db_column="text")

    class Meta:
        db_table = "note"

    def __str__(self) -> str:
        return f"nota:{self.pk}"
