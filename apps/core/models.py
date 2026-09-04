"""Modelos transversales de UniCare.

Este modulo contiene:

  * `Auditor`  - modelo abstracto con los campos de auditoria del DER.
  * `User`     - la entidad USER del DER.
  * `AuditLog` - la entidad AUDIT_LOG del DER.

Contrato: ver docs/DER_ANALYSIS.md y docs/DECISIONS.md.
"""

from __future__ import annotations

from django.contrib.auth.base_user import AbstractBaseUser
from django.core import validators
from django.db import models

from apps.core.choices import ENUM_MAX_LENGTH, AuditAction
from apps.core.managers import UserManager


class Auditor(models.Model):
    """Campos de auditoria definidos por el DER.

    Se aplica EXCLUSIVAMENTE a las 11 tablas a las que el DER dota de los
    cuatro campos. `USER`, `AUDIT_LOG` y `APPOINTMENT_REMINDER` NO lo heredan,
    porque el DER no les define esas columnas (docs/DER_ANALYSIS.md, D-02).
    """

    created_at = models.DateTimeField(
        auto_now_add=True, db_column="created_at", editable=False
    )
    updated_at = models.DateTimeField(
        auto_now=True, db_column="updated_at", editable=False
    )
    # DEC-04: SET_NULL. El DER declara ambas columnas nullable, asi que borrar
    # un usuario no puede arrastrar registros clinicos.
    created_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_column="created_by",
        related_name="+",
    )
    updated_by = models.ForeignKey(
        "core.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        db_column="updated_by",
        related_name="+",
    )

    class Meta:
        abstract = True


class User(AbstractBaseUser):
    """Entidad `USER` del DER.

    Columnas del DER: user_id (PK), username (UNIQUE), email (UNIQUE),
    is_active (NOT NULL), created_at (NOT NULL), updated_at (NOT NULL).

    Delta autorizado sobre el DER (docs/DECISIONS.md seccion 3), heredado de
    `AbstractBaseUser` y sin el cual JWT es imposible:

      * `password`   varchar(128) NOT NULL
      * `last_login` timestamptz NULL

    NO se usa `PermissionsMixin`: eso anadiria `is_superuser` y dos tablas M2M
    que el DER no contempla.
    """

    user_id = models.BigAutoField(primary_key=True, db_column="user_id")
    # DEC-01: el DER escribe `varchar` sin longitud -> TextField (text), para
    # no inventar un limite que el contrato no declara.
    username = models.TextField(
        unique=True, null=True, blank=True, db_column="username"
    )
    # El DER declara `varchar` sin longitud tambien aqui, asi que NO se usa
    # EmailField (que impondria un max_length=254 inexistente en el contrato).
    # La validacion de formato se conserva con el validador explicito.
    email = models.TextField(
        unique=True,
        null=True,
        blank=True,
        db_column="email",
        validators=[validators.EmailValidator()],
    )
    is_active = models.BooleanField(default=True, db_column="is_active")
    created_at = models.DateTimeField(
        auto_now_add=True, db_column="created_at", editable=False
    )
    updated_at = models.DateTimeField(
        auto_now=True, db_column="updated_at", editable=False
    )

    objects = UserManager()

    USERNAME_FIELD = "username"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        db_table = "user"  # DEC-09
        verbose_name = "user"
        verbose_name_plural = "users"

    def __str__(self) -> str:
        return self.username or f"user:{self.pk}"


class AuditLog(models.Model):
    """Entidad `AUDIT_LOG` del DER.

    NO hereda de `Auditor`: el DER solo le define `created_at`. No tiene
    `updated_at`, `created_by` ni `updated_by`, y no se le anaden.

    El DER tampoco define una columna `changes`; los cambios realizados se
    derivan en lectura del diff entre `old_values` y `new_values`
    (docs/DER_ANALYSIS.md, D-03).
    """

    audit_id = models.BigAutoField(primary_key=True, db_column="audit_id")
    # DEC-04: PROTECT. `user_id` es NOT NULL en el DER, asi que un usuario con
    # auditoria asociada no puede borrarse sin romper la integridad.
    user = models.ForeignKey(
        "core.User",
        on_delete=models.PROTECT,
        db_column="user_id",
        related_name="audit_logs",
    )
    entity_type = models.CharField(max_length=100, db_column="entity_type")
    # No es FK: apunta a cualquier entidad auditada, identificada por
    # `entity_type`. El DER lo declara como bigint suelto.
    entity_id = models.BigIntegerField(db_column="entity_id")
    action = models.CharField(
        max_length=ENUM_MAX_LENGTH,
        choices=AuditAction.choices,
        null=True,
        blank=True,
        db_column="action",
    )
    old_values = models.JSONField(null=True, blank=True, db_column="old_values")
    new_values = models.JSONField(null=True, blank=True, db_column="new_values")
    created_at = models.DateTimeField(
        auto_now_add=True, db_column="created_at", editable=False
    )

    class Meta:
        db_table = "audit_log"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action__in=AuditAction.values)
                | models.Q(action__isnull=True),
                name="ck_audit_log_action",
            ),
        ]
        # DEC-05: indices no unicos, no alteran el contrato del DER.
        indexes = [
            models.Index(
                fields=["entity_type", "entity_id"], name="ix_audit_log_entity"
            ),
            models.Index(fields=["created_at"], name="ix_audit_log_created_at"),
        ]

    def __str__(self) -> str:
        return f"{self.action} {self.entity_type}:{self.entity_id}"
