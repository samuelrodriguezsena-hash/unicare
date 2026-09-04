"""Modelos de `massive_load`: importacion masiva de pacientes y patologias.

Entidades del DER implementadas aqui:

    IMPORT_BATCH, IMPORT_BATCH_ROW
"""

from __future__ import annotations

from django.db import models

from apps.core.choices import ENUM_MAX_LENGTH
from apps.core.models import Auditor
from apps.massive_load.choices import ImportBatchRowStatus, ImportBatchStatus


class ImportBatch(Auditor):
    """Entidad `IMPORT_BATCH` del DER.

    Los tres contadores (`total_rows`, `success_count`, `failure_count`) son
    nullable en el DER: estan vacios hasta que el lote se procesa.
    """

    import_batch_id = models.BigAutoField(primary_key=True, db_column="import_batch_id")
    source_file_name = models.CharField(max_length=255, db_column="source_file_name")
    source_file_type = models.CharField(
        max_length=50, null=True, blank=True, db_column="source_file_type"
    )
    processed_at = models.DateTimeField(null=True, blank=True, db_column="processed_at")
    total_rows = models.IntegerField(null=True, blank=True, db_column="total_rows")
    success_count = models.IntegerField(
        null=True, blank=True, db_column="success_count"
    )
    failure_count = models.IntegerField(
        null=True, blank=True, db_column="failure_count"
    )
    status = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=ImportBatchStatus.choices,
        null=True,
        blank=True,
        db_column="status",
    )

    class Meta:
        db_table = "import_batch"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ImportBatchStatus.values)
                | models.Q(status__isnull=True),
                name="ck_import_batch_status",
            ),
        ]

    def __str__(self) -> str:
        return self.source_file_name


class ImportBatchRow(Auditor):
    """Entidad `IMPORT_BATCH_ROW` del DER.

    D-04: el DER NO define FK al `PATIENT` creado o encontrado. La trazabilidad
    fila -> entidad es unicamente por `identification_number` y por los dos
    campos de snapshot. No se anade una FK que el contrato no declara.
    """

    import_batch_row_id = models.BigAutoField(
        primary_key=True, db_column="import_batch_row_id"
    )
    import_batch = models.ForeignKey(
        "massive_load.ImportBatch",
        on_delete=models.CASCADE,
        db_column="import_batch_id",
        related_name="rows",
    )
    row_number = models.IntegerField(db_column="row_number")
    identification_number = models.CharField(
        max_length=50, null=True, blank=True, db_column="identification_number"
    )
    patient_name_snapshot = models.CharField(
        max_length=255, null=True, blank=True, db_column="patient_name_snapshot"
    )
    pathology_name_snapshot = models.CharField(
        max_length=255, null=True, blank=True, db_column="pathology_name_snapshot"
    )
    status = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=ImportBatchRowStatus.choices,
        null=True,
        blank=True,
        db_column="status",
    )
    # Motivo del error por fila: "ID de paciente no encontrado",
    # "Formato de fecha incorrecto", etc.
    error_message = models.TextField(null=True, blank=True, db_column="error_message")

    class Meta:
        db_table = "import_batch_row"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ImportBatchRowStatus.values)
                | models.Q(status__isnull=True),
                name="ck_import_batch_row_status",
            ),
        ]

    def __str__(self) -> str:
        return f"fila {self.row_number} de lote {self.import_batch_id}"
