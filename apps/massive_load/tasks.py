"""Tareas Celery de la carga masiva."""

from __future__ import annotations

import logging
from typing import Any

from celery import shared_task

from apps.core.context import acting_as
from apps.core.models import User
from apps.massive_load.models import ImportBatch
from apps.massive_load.services.import_batches import ImportService

logger = logging.getLogger(__name__)


@shared_task(name="apps.massive_load.tasks.process_import_batch")
def process_import_batch(
    import_batch_id: int,
    filas: list[dict[str, Any]],
    user_id: int | None = None,
) -> dict[str, int]:
    """Procesa un lote ya registrado.

    Las filas viajan como argumento porque el DER no define ninguna columna
    donde guardar el archivo subido (DEC-32).

    El usuario que lanzo la importacion se propaga con `acting_as` para que la
    auditoria atribuya los pacientes y patologias creados a quien corresponde,
    y no al usuario tecnico `system` (C-04).
    """
    lote = ImportBatch.objects.filter(pk=import_batch_id).first()
    if lote is None:
        logger.info("Lote %s ya no existe; nada que procesar", import_batch_id)
        return {"total": 0, "success": 0, "failure": 0}

    usuario = User.objects.filter(pk=user_id).first() if user_id else None

    try:
        with acting_as(usuario):
            lote = ImportService().process(lote, filas)
    except Exception as exc:
        # Un fallo aqui NO es de una fila: es del lote entero. Las filas ya
        # procesadas conservan su resultado.
        ImportService.mark_failed(lote, str(exc))
        raise

    return {
        "total": lote.total_rows or 0,
        "success": lote.success_count or 0,
        "failure": lote.failure_count or 0,
    }
