"""Servicio de auditoria.

Construye y persiste `AUDIT_LOG` respetando exactamente su estructura del DER:
no se anaden columnas, y en particular NO existe una columna `changes` — los
cambios realizados se derivan en lectura del diff entre `old_values` y
`new_values` (docs/DER_ANALYSIS.md, D-03).

Responsable de la operacion (docs/DECISIONS.md, C-04): `AUDIT_LOG.user_id` es
NOT NULL en el DER, pero las tareas Celery y los comandos de gestion no tienen
usuario autenticado. Se resuelve asi:

  1. el usuario de la peticion HTTP en curso, si lo hay;
  2. en su defecto, el usuario tecnico `system`.

Privacidad: `old_values`/`new_values` guardan datos clinicos porque el DER asi
lo exige, pero los campos sensibles de credenciales NUNCA se registran, y este
servicio no escribe nada de ese contenido en los logs de aplicacion.
"""

from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db.models import Model

from apps.core.choices import AuditAction
from apps.core.context import get_current_user

logger = logging.getLogger(__name__)

# Nunca se auditan: guardar un hash de contrasena en jsonb seria filtrarlo.
SENSITIVE_FIELDS: frozenset[str] = frozenset({"password", "last_login"})


class SystemUserMissingError(RuntimeError):
    """No existe el usuario tecnico y la operacion no tiene usuario asociado.

    Indica que falta aplicar la data migration `core.0002_system_user`.
    """


def to_jsonable(value: Any) -> Any:
    """Convierte un valor de modelo en algo que `jsonb` admita."""
    if value is None or isinstance(value, bool | int | float | str):
        return value
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, dict | list):
        return value
    return str(value)


def serialize_instance(instance: Model) -> dict[str, Any]:
    """Instantanea de una instancia, indexada por NOMBRE FISICO de columna.

    Se usa la columna y no el atributo Python para que la auditoria hable el
    mismo idioma que el DER.
    """
    datos: dict[str, Any] = {}
    for field in instance._meta.concrete_fields:
        if field.attname in SENSITIVE_FIELDS or field.column in SENSITIVE_FIELDS:
            continue
        datos[field.column] = to_jsonable(getattr(instance, field.attname, None))
    return datos


def diff(anterior: dict[str, Any], nuevo: dict[str, Any]) -> list[str]:
    """Columnas cuyo valor cambio. Base del `changes` derivado (D-03)."""
    claves = set(anterior) | set(nuevo)
    return sorted(k for k in claves if anterior.get(k) != nuevo.get(k))


class AuditService:
    """Punto unico de escritura de `AUDIT_LOG`."""

    @staticmethod
    def entity_type(instance: Model) -> str:
        """Nombre fisico de la tabla, tal y como la nombra el DER."""
        return instance._meta.db_table

    @staticmethod
    def resolve_user_id() -> int:
        """PK del responsable de la operacion.

        Solo consulta la base cuando NO hay usuario en la peticion, es decir en
        tareas Celery y comandos. En una peticion HTTP no cuesta ninguna query.
        """
        user = get_current_user()
        if user is not None and user.pk is not None:
            return int(user.pk)

        from apps.core.models import User

        system_id = (
            User.objects.filter(username=settings.SYSTEM_USERNAME)
            .values_list("pk", flat=True)
            .first()
        )
        if system_id is None:
            raise SystemUserMissingError(
                f"No existe el usuario tecnico '{settings.SYSTEM_USERNAME}'. "
                "Aplica la migracion core.0002_system_user."
            )
        return int(system_id)

    @classmethod
    def log(
        cls,
        instance: Model,
        action: str,
        old_values: dict[str, Any] | None = None,
        new_values: dict[str, Any] | None = None,
    ) -> Model | None:
        """Registra una operacion. Devuelve el `AuditLog` creado.

        Una auditoria que falla no debe tumbar la operacion de negocio que la
        origino, asi que el fallo se registra y se reporta, pero no se propaga.
        """
        from apps.core.models import AuditLog

        try:
            return AuditLog.objects.create(
                user_id=cls.resolve_user_id(),
                entity_type=cls.entity_type(instance),
                entity_id=instance.pk,
                action=action,
                old_values=old_values,
                new_values=new_values,
            )
        except Exception:
            # No se registra el contenido: puede incluir informacion clinica.
            logger.exception(
                "No se pudo auditar %s sobre %s:%s",
                action,
                cls.entity_type(instance),
                instance.pk,
            )
            return None

    @classmethod
    def log_create(cls, instance: Model) -> Model | None:
        return cls.log(instance, AuditAction.CREATE, None, serialize_instance(instance))

    @classmethod
    def log_update(cls, instance: Model, previous: dict[str, Any]) -> Model | None:
        """Registra una modificacion.

        Se guardan UNICAMENTE las columnas que cambiaron, en ambos lados. El DER
        no obliga a guardar la instantanea completa, y limitarlo al cambio hace
        que `AUDIT_LOG` responda directamente a "que se modifico" sin inflar el
        jsonb en cada guardado.

        Si no cambio nada, no se registra nada: un `save()` sin cambios no es
        una operacion auditable.
        """
        actual = serialize_instance(instance)
        cambiadas = diff(previous, actual)
        if not cambiadas:
            return None
        return cls.log(
            instance,
            AuditAction.UPDATE,
            {k: previous.get(k) for k in cambiadas},
            {k: actual.get(k) for k in cambiadas},
        )

    @classmethod
    def log_delete(cls, instance: Model, previous: dict[str, Any]) -> Model | None:
        return cls.log(instance, AuditAction.DELETE, previous, None)
