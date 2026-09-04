"""Vistas de `massive_load`."""

from __future__ import annotations

import csv

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAuthenticatedAndActive
from apps.core.validators import validate_import_file_extension
from apps.core.views import Echo
from apps.massive_load import tasks
from apps.massive_load.models import ImportBatch, ImportBatchRow
from apps.massive_load.parsers import ImportParseError, parse
from apps.massive_load.serializers import (
    ImportBatchRowSerializer,
    ImportBatchSerializer,
    ImportBatchUploadSerializer,
)
from apps.massive_load.services.import_batches import ImportService


class ImportBatchListCreateView(ListAPIView):
    """`GET/POST /api/v1/import-batches/`.

    La subida parsea el archivo de forma sincrona (para poder rechazar de
    inmediato uno mal formado) y encola el procesamiento, que puede ser largo.
    """

    permission_classes = [IsAuthenticatedAndActive]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ImportBatchSerializer
    filterset_fields = ["status"]
    ordering_fields = ["created_at", "processed_at"]
    ordering = ["-created_at"]

    def get_queryset(self) -> QuerySet[ImportBatch]:
        return ImportBatch.objects.all()

    def post(self, request: Request) -> Response:
        entrada = ImportBatchUploadSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        archivo = entrada.validated_data["file"]

        try:
            extension = validate_import_file_extension(archivo.name)
            filas = parse(archivo.read(), extension)
        except (ImportParseError, DjangoValidationError) as exc:
            # El archivo entero es inservible: no hay nada que importar.
            raise ValidationError({"file": exc.messages}) from exc

        if not filas:
            raise ValidationError({"file": ["El archivo no contiene filas."]})

        lote = ImportService.create_batch(archivo.name, extension, filas)
        tasks.process_import_batch.delay(lote.pk, filas, request.user.pk)

        return Response(
            ImportBatchSerializer(lote).data, status=status.HTTP_202_ACCEPTED
        )


class ImportBatchDetailView(RetrieveAPIView):
    """`GET /api/v1/import-batches/{id}/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = ImportBatchSerializer
    queryset = ImportBatch.objects.all()
    lookup_field = "import_batch_id"
    lookup_url_kwarg = "import_batch_id"


class ImportBatchRowListView(ListAPIView):
    """`GET /api/v1/import-batches/{id}/rows/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = ImportBatchRowSerializer
    filterset_fields = ["status"]

    def get_queryset(self) -> QuerySet[ImportBatchRow]:
        return ImportBatchRow.objects.filter(
            import_batch_id=self.kwargs["import_batch_id"]
        ).order_by("row_number")


class ImportBatchReportView(APIView):
    """`GET /api/v1/import-batches/{id}/report/` - reporte CSV.

    Permite determinar, para cada importacion: total procesado, exitos,
    errores y el motivo de cada error.
    """

    permission_classes = [IsAuthenticatedAndActive]

    COLUMNAS = (
        "row_number",
        "identification_number",
        "patient_name_snapshot",
        "pathology_name_snapshot",
        "status",
        "error_message",
    )

    def get(self, request: Request, import_batch_id: int) -> StreamingHttpResponse:
        lote = get_object_or_404(ImportBatch, pk=import_batch_id)
        respuesta = StreamingHttpResponse(self._filas(lote), content_type="text/csv")
        respuesta["Content-Disposition"] = (
            f'attachment; filename="import_batch_{lote.pk}.csv"'
        )
        return respuesta

    def _filas(self, lote: ImportBatch):
        escritor = csv.writer(Echo())
        yield escritor.writerow(self.COLUMNAS)
        for registro in lote.rows.order_by("row_number").iterator(chunk_size=500):
            yield escritor.writerow(
                (
                    registro.row_number,
                    registro.identification_number or "",
                    registro.patient_name_snapshot or "",
                    registro.pathology_name_snapshot or "",
                    registro.status or "",
                    registro.error_message or "",
                )
            )
