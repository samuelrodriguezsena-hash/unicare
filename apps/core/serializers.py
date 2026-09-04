"""Serializers de `core`."""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from apps.core.models import AuditLog
from apps.core.services.audit import diff


class AuditLogSerializer(serializers.ModelSerializer):
    """Representacion de una entrada de `AUDIT_LOG`.

    `changes` NO es una columna: el DER no define ninguna (D-03). Se deriva en
    lectura del diff entre `old_values` y `new_values`, que es exactamente lo
    que la documentacion pide poder conocer.
    """

    username = serializers.CharField(source="user.username", read_only=True)
    changes = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = (
            "audit_id",
            "user",
            "username",
            "entity_type",
            "entity_id",
            "action",
            "changes",
            "old_values",
            "new_values",
            "created_at",
        )
        read_only_fields = fields

    def get_changes(self, obj: AuditLog) -> list[str]:
        return diff(obj.old_values or {}, obj.new_values or {})


class AuditLogExportSerializer(serializers.Serializer):
    """Valida los filtros admitidos por la exportacion CSV."""

    entity_type = serializers.CharField(required=False)
    entity_id = serializers.IntegerField(required=False)
    user = serializers.IntegerField(required=False)
    action = serializers.CharField(required=False)
    created_at_after = serializers.DateTimeField(required=False)
    created_at_before = serializers.DateTimeField(required=False)

    def to_filters(self) -> dict[str, Any]:
        datos = dict(self.validated_data)
        filtros: dict[str, Any] = {}
        for campo, lookup in (
            ("entity_type", "entity_type"),
            ("entity_id", "entity_id"),
            ("user", "user_id"),
            ("action", "action"),
            ("created_at_after", "created_at__gte"),
            ("created_at_before", "created_at__lte"),
        ):
            if campo in datos:
                filtros[lookup] = datos[campo]
        return filtros
