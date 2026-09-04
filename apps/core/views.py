"""Vistas transversales: health checks.

Separacion deliberada:

  * /health/       liveness  - responde si el proceso esta vivo. No toca nada.
  * /health/ready/ readiness - verifica las dependencias criticas.

La readiness NO depende de Gemini ni de la API de farmacos: una caida de un
proveedor externo no debe sacar el backend del balanceador.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Iterator

import django_filters
from django.core.cache import cache
from django.db import connections
from django.http import StreamingHttpResponse
from rest_framework import status
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import AuditLog
from apps.core.permissions import CanReadAuditLog
from apps.core.serializers import AuditLogExportSerializer, AuditLogSerializer
from apps.core.services.audit import diff

logger = logging.getLogger(__name__)


class HealthView(APIView):
    """Liveness probe."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        return Response({"status": "ok"})


class ReadinessView(APIView):
    """Readiness probe: PostgreSQL y Redis."""

    permission_classes = [AllowAny]
    authentication_classes: list = []

    def get(self, request: Request) -> Response:
        checks = {
            "database": self._check_database(),
            "cache": self._check_cache(),
        }
        ready = all(checks.values())
        return Response(
            {"status": "ready" if ready else "not-ready", "checks": checks},
            status=(
                status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE
            ),
        )

    @staticmethod
    def _check_database() -> bool:
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception:
            logger.exception("Readiness: PostgreSQL no responde")
            return False
        return True

    @staticmethod
    def _check_cache() -> bool:
        try:
            cache.set("unicare:readiness", "1", timeout=10)
            return cache.get("unicare:readiness") == "1"
        except Exception:
            logger.exception("Readiness: Redis no responde")
            return False


class AuditLogFilterSet(django_filters.FilterSet):
    """Filtros de consulta de auditoria."""

    created_at_after = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="gte"
    )
    created_at_before = django_filters.IsoDateTimeFilter(
        field_name="created_at", lookup_expr="lte"
    )

    class Meta:
        model = AuditLog
        fields = ["entity_type", "entity_id", "user", "action"]


class AuditLogQuerysetMixin:
    """Consulta base de auditoria, con el usuario ya resuelto.

    `select_related("user")` evita el N+1 que produciria el `username` de cada
    fila del listado.
    """

    queryset = AuditLog.objects.select_related("user").order_by("-created_at")
    serializer_class = AuditLogSerializer
    permission_classes = [CanReadAuditLog]


class AuditLogListView(AuditLogQuerysetMixin, ListAPIView):
    """`GET /api/v1/audit-logs/` - listado paginado y filtrable."""

    filterset_class = AuditLogFilterSet


class AuditLogDetailView(AuditLogQuerysetMixin, RetrieveAPIView):
    """`GET /api/v1/audit-logs/{id}/` - detalle con los cambios derivados."""

    lookup_field = "audit_id"
    lookup_url_kwarg = "audit_id"


class AuditLogExportView(APIView):
    """`GET /api/v1/audit-logs/export/` - exportacion CSV.

    Se transmite en streaming y se recorre el queryset con `iterator()`: una
    auditoria puede tener millones de filas y no debe cargarse en memoria.
    """

    permission_classes = [CanReadAuditLog]

    COLUMNAS = (
        "audit_id",
        "created_at",
        "username",
        "entity_type",
        "entity_id",
        "action",
        "changes",
    )

    def get(self, request: Request) -> StreamingHttpResponse:
        serializer = AuditLogExportSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        registros = (
            AuditLog.objects.select_related("user")
            .filter(**serializer.to_filters())
            .order_by("-created_at")
        )
        respuesta = StreamingHttpResponse(
            self._filas(registros), content_type="text/csv"
        )
        respuesta["Content-Disposition"] = 'attachment; filename="audit_log.csv"'
        return respuesta

    def _filas(self, registros) -> Iterator[str]:
        escritor = csv.writer(Echo())
        yield escritor.writerow(self.COLUMNAS)
        for registro in registros.iterator(chunk_size=500):
            yield escritor.writerow(
                (
                    registro.audit_id,
                    registro.created_at.isoformat(),
                    registro.user.username if registro.user_id else "",
                    registro.entity_type,
                    registro.entity_id,
                    registro.action or "",
                    # Solo los nombres de las columnas modificadas: el CSV de
                    # auditoria no debe difundir contenido clinico.
                    " ".join(
                        diff(registro.old_values or {}, registro.new_values or {})
                    ),
                )
            )


class Echo:
    """Buffer de escritura que devuelve lo escrito, para `csv` en streaming."""

    def write(self, value: str) -> str:
        return value
