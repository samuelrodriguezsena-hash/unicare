"""Dominios enumerados de `massive_load`.

Valores fijados en docs/DECISIONS.md seccion 4 (DEC-03).

`COMPLETED_WITH_ERRORS` existe porque la documentacion exige que una fila
invalida NO detenga necesariamente toda la carga: un lote puede terminar con
exitos y errores a la vez.
"""

from __future__ import annotations

from django.db import models


class ImportBatchStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    PROCESSING = "PROCESSING", "Procesando"
    COMPLETED = "COMPLETED", "Completado"
    COMPLETED_WITH_ERRORS = "COMPLETED_WITH_ERRORS", "Completado con errores"
    FAILED = "FAILED", "Fallido"


class ImportBatchRowStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    SUCCESS = "SUCCESS", "Exito"
    ERROR = "ERROR", "Error"
