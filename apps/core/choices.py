"""Dominios enumerados de `core`.

DEC-10: el DER declara `enum(...)`. Se implementan como `CharField` +
`TextChoices` + `CheckConstraint`, no como tipos ENUM nativos de PostgreSQL,
porque Django no gestiona estos ultimos de forma reproducible en migraciones.
El dominio cerrado de valores se conserva mediante la restriccion CHECK.

Los valores concretos estan fijados en docs/DECISIONS.md seccion 4.
"""

from __future__ import annotations

from django.db import models

# Longitud de las columnas enum. El DER no declara longitud para `enum(...)`;
# 30 es un detalle de implementacion de DEC-10, holgado para todos los valores
# definidos, y coincide con los varchar(30) que el DER si dimensiona
# (priority_suggested_by_ai, priority_final, validation_status).
ENUM_MAX_LENGTH = 30


class AuditAction(models.TextChoices):
    CREATE = "CREATE", "Creacion"
    UPDATE = "UPDATE", "Actualizacion"
    DELETE = "DELETE", "Eliminacion"
