"""Managers de `core`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from django.contrib.auth.base_user import BaseUserManager

if TYPE_CHECKING:  # pragma: no cover
    from apps.core.models import User


class UserManager(BaseUserManager):
    """Manager de `core.User`.

    El DER no define `is_staff` ni `is_superuser` y la implementacion no usa
    `PermissionsMixin` (docs/DECISIONS.md, C-02 opcion 3). En consecuencia no
    existen niveles de privilegio distintos: todo usuario activo tiene las
    mismas capacidades.

    `create_superuser` se mantiene como alias de `create_user` para que
    `manage.py createsuperuser` siga siendo un paso reproducible del
    deployment, no para conceder privilegios adicionales.
    """

    use_in_migrations = True

    def create_user(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        if not username:
            raise ValueError("El usuario requiere un username.")
        user = self.model(
            username=username,
            email=self.normalize_email(email) if email else None,
            **extra_fields,
        )
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.full_clean(exclude=["password", "last_login"])
        user.save(using=self._db)
        return user

    def create_superuser(
        self,
        username: str,
        email: str | None = None,
        password: str | None = None,
        **extra_fields: Any,
    ) -> User:
        return self.create_user(username, email, password, **extra_fields)
