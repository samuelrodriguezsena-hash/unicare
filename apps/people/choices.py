"""Dominios enumerados de `people`.

Valores fijados en docs/DECISIONS.md seccion 4 (DEC-03). El DER declara
`enum(entry_type)` sin enumerar los valores.
"""

from __future__ import annotations

from django.db import models


class ClinicalHistoryEntryType(models.TextChoices):
    DIAGNOSIS = "DIAGNOSIS", "Diagnostico"
    TREATMENT = "TREATMENT", "Tratamiento"
    OBSERVATION = "OBSERVATION", "Observacion"
    PROCEDURE = "PROCEDURE", "Procedimiento"
    FOLLOW_UP = "FOLLOW_UP", "Seguimiento"
