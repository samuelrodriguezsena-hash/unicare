"""Serializers de `massive_load`."""

from __future__ import annotations

from rest_framework import serializers

from apps.core.validators import validate_import_file_extension
from apps.massive_load.models import ImportBatch, ImportBatchRow


class ImportBatchRowSerializer(serializers.ModelSerializer):
    """Resultado de una fila. De solo lectura: lo produce el procesamiento."""

    class Meta:
        model = ImportBatchRow
        fields = (
            "import_batch_row_id",
            "row_number",
            "identification_number",
            "patient_name_snapshot",
            "pathology_name_snapshot",
            "status",
            "error_message",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ImportBatchSerializer(serializers.ModelSerializer):
    """Estado y contadores de un lote."""

    class Meta:
        model = ImportBatch
        fields = (
            "import_batch_id",
            "source_file_name",
            "source_file_type",
            "status",
            "total_rows",
            "success_count",
            "failure_count",
            "processed_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class ImportBatchUploadSerializer(serializers.Serializer):
    """Subida de un archivo de carga masiva.

    Solo valida el continente: nombre y extension. El contenido lo valida el
    parser, y los datos de negocio se validan fila a fila durante el
    procesamiento, para que un dato incorrecto no invalide el archivo entero.
    """

    file = serializers.FileField()

    def validate_file(self, archivo):
        from django.core.exceptions import ValidationError as DjangoValidationError

        try:
            validate_import_file_extension(archivo.name)
        except DjangoValidationError as exc:
            raise serializers.ValidationError(exc.messages) from exc
        return archivo
