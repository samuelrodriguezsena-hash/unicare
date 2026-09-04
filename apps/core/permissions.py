"""Politica de permisos, separada de la logica de negocio.

docs/DECISIONS.md, C-03: el DER no define roles en `USER` (no hay `role`, ni
`is_staff`, ni relacion con grupos), asi que este sistema NO distingue perfiles.
La regla vigente es: ninguna operacion administrativa sin usuario autenticado
y activo.

Todo esta concentrado aqui a proposito. Cuando se autorice anadir una columna
`role` a `USER`, el cambio se limita a este modulo: las vistas no cambian.
"""

from __future__ import annotations

from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView


class IsAuthenticatedAndActive(BasePermission):
    """Exige un usuario autenticado y con `is_active` verdadero.

    `is_active` es la unica dimension de autorizacion que el DER contempla.
    """

    message = "Se requiere un usuario autenticado y activo."

    def has_permission(self, request: Request, view: APIView) -> bool:
        user = getattr(request, "user", None)
        return bool(
            user is not None
            and getattr(user, "is_authenticated", False)
            and getattr(user, "is_active", False)
        )


class ReadOnly(BasePermission):
    """Permite solo metodos seguros.

    Se combina con la anterior para exponer recursos de consulta, como la
    auditoria, que nunca debe modificarse por API.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:
        return request.method in {"GET", "HEAD", "OPTIONS"}


class CanReadAuditLog(IsAuthenticatedAndActive):
    """Consulta de auditoria.

    Hoy equivale a estar autenticado y activo. Existe como clase propia para
    que restringirla a un rol auditor sea un cambio de una linea, aqui.
    """

    message = "Se requiere un usuario autenticado y activo para consultar la auditoria."

    def has_permission(self, request: Request, view: APIView) -> bool:
        return super().has_permission(request, view) and ReadOnly().has_permission(
            request, view
        )


def describe_policy() -> dict[str, Any]:
    """Resumen legible de la politica vigente, para documentacion y tests."""
    return {
        "roles": False,
        "motivo": "El DER no define roles en USER (docs/DECISIONS.md, C-03).",
        "regla": "Autenticado y activo para toda operacion administrativa.",
    }
