"""Rutas transversales de UniCare: autenticacion, auditoria y health checks."""

from __future__ import annotations

from django.urls import path
from rest_framework_simplejwt.views import (
    TokenObtainPairView,
    TokenRefreshView,
    TokenVerifyView,
)

from apps.core.views import (
    AuditLogDetailView,
    AuditLogExportView,
    AuditLogListView,
    HealthView,
    ReadinessView,
)

app_name = "core"

urlpatterns = [
    # Autenticacion. Son los UNICOS endpoints publicos junto a los health
    # checks: sin ellos no habria forma de obtener un token.
    path("auth/token/", TokenObtainPairView.as_view(), name="token-obtain"),
    path("auth/token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("auth/token/verify/", TokenVerifyView.as_view(), name="token-verify"),
    path("health/", HealthView.as_view(), name="health"),
    path("health/ready/", ReadinessView.as_view(), name="health-ready"),
    # `export/` va antes que `<int:audit_id>/` para que no lo capture el detalle.
    path("audit-logs/export/", AuditLogExportView.as_view(), name="audit-log-export"),
    path("audit-logs/", AuditLogListView.as_view(), name="audit-log-list"),
    path(
        "audit-logs/<int:audit_id>/",
        AuditLogDetailView.as_view(),
        name="audit-log-detail",
    ),
]
