"""Dominios enumerados de `medications`.

Valores fijados en docs/DECISIONS.md seccion 4 (DEC-03).
"""

from __future__ import annotations

from django.db import models


class TreatmentPlanStatus(models.TextChoices):
    DRAFT = "DRAFT", "Borrador"
    ACTIVE = "ACTIVE", "Activo"
    COMPLETED = "COMPLETED", "Completado"
    CANCELLED = "CANCELLED", "Cancelado"


class MedicationValidationStatus(models.TextChoices):
    """Estado de la validacion cruzada contra la API externa de farmacos.

    El DER declara `validation_status` como `varchar(30)`, NO como enum. Por eso
    estos valores se aplican a nivel de aplicacion y NO llevan `CheckConstraint`:
    imponer una restriccion que el DER no declara alteraria el contrato.
    """

    PENDING = "PENDING", "Pendiente de validacion"
    VALIDATED = "VALIDATED", "Validado"
    WARNING = "WARNING", "Con advertencia"
