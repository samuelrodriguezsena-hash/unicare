"""Importacion masiva de pacientes y patologias.

Flujo:

    Archivo -> validacion -> filas persistidas -> procesamiento -> reporte

Dos decisiones que conviene tener presentes:

DEC-32: el DER NO define ninguna columna donde guardar el archivo subido, solo
`source_file_name` y `source_file_type`. En vez de anadir una, el archivo se
parsea al subirlo y cada linea se persiste como `IMPORT_BATCH_ROW`, que ya
tiene exactamente los snapshots necesarios. El archivo no se retiene: las filas
SON el estado intermedio. Asi el procesamiento asincrono no necesita
almacenamiento externo ni columnas nuevas.

C-05 / documentacion: **una fila invalida NO detiene la carga.** Cada fila se
procesa en su propia transaccion; un fallo la marca ERROR con su motivo y el
resto continua.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from django.core.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.core.validators import validate_identification_number
from apps.massive_load.choices import ImportBatchRowStatus, ImportBatchStatus
from apps.massive_load.models import ImportBatch, ImportBatchRow
from apps.people.models import Pathology, Patient, PatientPathology

logger = logging.getLogger(__name__)

# Formatos de fecha admitidos en el archivo, en orden de preferencia.
FORMATOS_DE_FECHA = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y")

MAX_ERROR = 1000
VERDADEROS = {"1", "true", "si", "sí", "yes", "y", "x"}


class RowError(Exception):
    """Error de una fila concreta. No aborta el lote."""


def parse_fecha(valor: str | None, campo: str) -> date | None:
    """Convierte una fecha del archivo, o falla con un motivo legible.

    Siempre recibe texto: el parser ya normaliza a ISO las celdas de fecha que
    openpyxl devuelve como `datetime`.
    """
    if valor is None:
        return None

    for formato in FORMATOS_DE_FECHA:
        try:
            return datetime.strptime(str(valor), formato).date()
        except ValueError:
            continue
    raise RowError(f"Formato de fecha incorrecto en '{campo}': {valor}")


def parse_booleano(valor: str | None) -> bool | None:
    if valor is None:
        return None
    return str(valor).strip().lower() in VERDADEROS


class ImportService:
    """Crea lotes de importacion y los procesa fila a fila."""

    # ------------------------------------------------------------------
    # Creacion del lote
    # ------------------------------------------------------------------
    @staticmethod
    @transaction.atomic
    def create_batch(
        nombre_archivo: str, extension: str, filas: list[dict[str, Any]]
    ) -> ImportBatch:
        """Registra el lote y persiste sus filas como PENDING.

        El lote y sus filas se crean juntos: un lote sin filas seria un estado
        intermedio que nadie podria procesar despues.
        """
        lote = ImportBatch.objects.create(
            source_file_name=nombre_archivo,
            source_file_type=extension,
            total_rows=len(filas),
            success_count=0,
            failure_count=0,
            status=ImportBatchStatus.PENDING,
        )
        ImportBatchRow.objects.bulk_create(
            [
                ImportBatchRow(
                    import_batch=lote,
                    row_number=numero,
                    identification_number=(fila.get("identification_number") or "")[:50]
                    or None,
                    patient_name_snapshot=ImportService._nombre(fila),
                    pathology_name_snapshot=(fila.get("pathology") or "")[:255] or None,
                    status=ImportBatchRowStatus.PENDING,
                )
                for numero, fila in enumerate(filas, start=1)
            ]
        )
        # Los datos completos de cada fila no caben en el DER; solo se guardan
        # los snapshots. El resto viaja a la tarea que procesa el lote.
        lote._filas = filas  # type: ignore[attr-defined]
        return lote

    @staticmethod
    def _nombre(fila: dict[str, Any]) -> str | None:
        partes = [fila.get("first_name"), fila.get("last_name")]
        nombre = " ".join(p for p in partes if p).strip()
        return nombre[:255] or None

    # ------------------------------------------------------------------
    # Procesamiento
    # ------------------------------------------------------------------
    def process(self, lote: ImportBatch, filas: list[dict[str, Any]]) -> ImportBatch:
        """Procesa todas las filas del lote y actualiza sus contadores."""
        lote.status = ImportBatchStatus.PROCESSING
        lote.save(update_fields=["status", "updated_at", "updated_by"])

        registros = {
            registro.row_number: registro
            for registro in lote.rows.order_by("row_number")
        }

        exitos = fallos = 0
        for numero, datos in enumerate(filas, start=1):
            registro = registros.get(numero)
            if registro is None:
                continue
            if self._process_row(registro, datos):
                exitos += 1
            else:
                fallos += 1

        lote.success_count = exitos
        lote.failure_count = fallos
        lote.processed_at = timezone.now()
        lote.status = (
            ImportBatchStatus.COMPLETED
            if fallos == 0
            else ImportBatchStatus.COMPLETED_WITH_ERRORS
        )
        lote.save(
            update_fields=[
                "success_count",
                "failure_count",
                "processed_at",
                "status",
                "updated_at",
                "updated_by",
            ]
        )
        return lote

    def _process_row(self, registro: ImportBatchRow, datos: dict[str, Any]) -> bool:
        """Procesa UNA fila en su propia transaccion.

        Devuelve True si tuvo exito. Un fallo se registra en la fila y no se
        propaga: la documentacion exige que una fila invalida no detenga
        necesariamente toda la carga.
        """
        try:
            with transaction.atomic():
                paciente = self._upsert_patient(datos)
                self._attach_pathology(paciente, datos)
        except (RowError, ValidationError) as exc:
            return self._marcar_error(registro, self._mensaje(exc))
        except DatabaseError as exc:
            logger.warning("Fila %s con error de base de datos", registro.row_number)
            return self._marcar_error(registro, self._mensaje(exc))

        registro.status = ImportBatchRowStatus.SUCCESS
        registro.error_message = None
        registro.save(update_fields=["status", "error_message", "updated_at"])
        return True

    @staticmethod
    def _mensaje(exc: Exception) -> str:
        if isinstance(exc, ValidationError):
            return " ".join(exc.messages)
        return str(exc)

    @staticmethod
    def _marcar_error(registro: ImportBatchRow, motivo: str) -> bool:
        registro.status = ImportBatchRowStatus.ERROR
        registro.error_message = motivo[:MAX_ERROR]
        registro.save(update_fields=["status", "error_message", "updated_at"])
        return False

    # ------------------------------------------------------------------
    # Reglas por fila
    # ------------------------------------------------------------------
    @staticmethod
    def _upsert_patient(datos: dict[str, Any]) -> Patient:
        """Busca el paciente por identificacion; lo crea si no existe."""
        identificacion = validate_identification_number(
            datos.get("identification_number")
        )

        nombre = datos.get("first_name")
        apellido = datos.get("last_name")
        if not nombre or not apellido:
            raise RowError("Faltan datos requeridos: first_name, last_name.")

        paciente = Patient.objects.filter(identification_number=identificacion).first()
        if paciente is not None:
            return paciente

        return Patient.objects.create(
            identification_number=identificacion,
            first_name=nombre[:100],
            last_name=apellido[:100],
            date_of_birth=parse_fecha(datos.get("date_of_birth"), "date_of_birth"),
            phone=(datos.get("phone") or None),
            email=(datos.get("email") or None),
            address=(datos.get("address") or None),
        )

    @staticmethod
    def _attach_pathology(paciente: Patient, datos: dict[str, Any]) -> None:
        """Asocia la patologia, sin duplicar una que el paciente ya tenga."""
        nombre = datos.get("pathology")
        if not nombre:
            raise RowError("Faltan datos requeridos: pathology.")

        patologia, _ = Pathology.objects.get_or_create(name=nombre[:255])

        if PatientPathology.objects.filter(
            patient=paciente, pathology=patologia
        ).exists():
            # No es un error: reimportar un archivo no debe fallar por esto.
            return

        es_principal = parse_booleano(datos.get("is_primary"))
        if (
            es_principal
            and PatientPathology.objects.filter(
                patient=paciente, is_primary=True
            ).exists()
        ):
            # El DER solo admite una principal por paciente; se asocia igual,
            # pero como secundaria, en lugar de perder la fila entera.
            es_principal = False

        PatientPathology.objects.create(
            patient=paciente,
            pathology=patologia,
            is_primary=es_principal,
            diagnosis_date=parse_fecha(datos.get("diagnosis_date"), "diagnosis_date"),
            notes=datos.get("notes"),
        )

    # ------------------------------------------------------------------
    # Fallo global
    # ------------------------------------------------------------------
    @staticmethod
    def mark_failed(lote: ImportBatch, motivo: str) -> ImportBatch:
        """Marca el lote como fallido por un problema ajeno a las filas."""
        lote.status = ImportBatchStatus.FAILED
        lote.processed_at = timezone.now()
        lote.save(update_fields=["status", "processed_at", "updated_at", "updated_by"])
        logger.error("Lote %s fallido: %s", lote.pk, motivo)
        return lote
