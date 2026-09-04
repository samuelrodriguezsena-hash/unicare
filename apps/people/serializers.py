"""Serializers de `people`.

Se limitan a serializar, validar entrada y representar. Las reglas de negocio
(alta con historial, baja logica, asociacion de patologias) viven en
`apps/people/services/`.
"""

from __future__ import annotations

from datetime import date

from rest_framework import serializers

from apps.core.validators import validate_identification_number
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Note,
    Pathology,
    Patient,
    PatientPathology,
)


def _identificacion(valor: str) -> str:
    """Adapta el validador de `core` al formato de error de DRF."""
    from django.core.exceptions import ValidationError as DjangoValidationError

    try:
        return validate_identification_number(valor)
    except DjangoValidationError as exc:
        raise serializers.ValidationError(exc.messages) from exc


class PathologySerializer(serializers.ModelSerializer):
    class Meta:
        model = Pathology
        fields = ("pathology_id", "name", "description", "created_at", "updated_at")
        read_only_fields = ("pathology_id", "created_at", "updated_at")


class PathologyBriefSerializer(serializers.ModelSerializer):
    """Version reducida, para anidar sin arrastrar campos de auditoria."""

    class Meta:
        model = Pathology
        fields = ("pathology_id", "name")


class PatientPathologySerializer(serializers.ModelSerializer):
    pathology = PathologyBriefSerializer(read_only=True)
    pathology_id = serializers.PrimaryKeyRelatedField(
        queryset=Pathology.objects.all(), source="pathology", write_only=True
    )

    class Meta:
        model = PatientPathology
        fields = (
            "patient_pathology_id",
            "pathology",
            "pathology_id",
            "is_primary",
            "diagnosis_date",
            "notes",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("patient_pathology_id", "created_at", "updated_at")


class PatientPathologyBriefSerializer(serializers.ModelSerializer):
    pathology = PathologyBriefSerializer(read_only=True)

    class Meta:
        model = PatientPathology
        fields = ("patient_pathology_id", "pathology", "diagnosis_date")


class PatientSerializer(serializers.ModelSerializer):
    """Representacion de lectura de un paciente.

    `age` y `primary_pathology` son derivados: NO son columnas del DER y no
    alteran el modelo.
    """

    age = serializers.SerializerMethodField()
    primary_pathology = serializers.SerializerMethodField()

    class Meta:
        model = Patient
        fields = (
            "patient_id",
            "identification_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "age",
            "phone",
            "email",
            "address",
            "is_active",
            "primary_pathology",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_age(self, obj: Patient) -> int | None:
        if obj.date_of_birth is None:
            return None
        hoy = date.today()
        cumplido = (hoy.month, hoy.day) >= (
            obj.date_of_birth.month,
            obj.date_of_birth.day,
        )
        return hoy.year - obj.date_of_birth.year - (0 if cumplido else 1)

    def get_primary_pathology(self, obj: Patient) -> dict | None:
        """Usa el `prefetch_related` de la vista; no dispara consulta propia."""
        primarias = getattr(obj, "primarias", None)
        if primarias is None:
            primarias = [p for p in obj.pathologies.all() if p.is_primary]
        if not primarias:
            return None
        return PatientPathologyBriefSerializer(primarias[0]).data


class PatientWriteSerializer(serializers.ModelSerializer):
    """Alta y modificacion de pacientes.

    `identification_number` es OPCIONAL en el DER (A-01) pero la documentacion
    lo exige como dato minimo. Se impone aqui, en la entrada de la API, sin
    endurecer el esquema.

    `is_active` no es escribible: la baja se hace por su propio endpoint, para
    que quede como una operacion explicita y auditable.
    """

    identification_number = serializers.CharField(
        required=True, validators=[_identificacion]
    )

    class Meta:
        model = Patient
        fields = (
            "identification_number",
            "first_name",
            "last_name",
            "date_of_birth",
            "phone",
            "email",
            "address",
        )

    def validate_date_of_birth(self, valor: date | None) -> date | None:
        if valor is not None and valor > date.today():
            raise serializers.ValidationError(
                "La fecha de nacimiento no puede ser futura."
            )
        return valor

    def validate_identification_number(self, valor: str) -> str:
        return _identificacion(valor)


class ClinicalHistoryEntrySerializer(serializers.ModelSerializer):
    class Meta:
        model = ClinicalHistoryEntry
        fields = (
            "clinical_history_entry_id",
            "entry_type",
            "entry_date",
            "description",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("clinical_history_entry_id", "created_at", "updated_at")


class NoteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Note
        fields = ("note_id", "text", "created_at", "updated_at")
        read_only_fields = ("note_id", "created_at", "updated_at")


class ClinicalHistorySerializer(serializers.ModelSerializer):
    """Historial completo de un paciente.

    Incluye entradas y notas, que se traen con `prefetch_related` desde la
    vista para no incurrir en N+1.
    """

    entries = ClinicalHistoryEntrySerializer(many=True, read_only=True)
    notes = NoteSerializer(many=True, read_only=True)
    pathologies = serializers.SerializerMethodField()

    class Meta:
        model = ClinicalHistory
        fields = (
            "clinical_history_id",
            "patient",
            "pathologies",
            "entries",
            "notes",
            "last_ai_summary",
            "last_ai_summary_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_pathologies(self, obj: ClinicalHistory) -> list[dict]:
        """Las patologias cuelgan del paciente, no del historial.

        El DER las asocia en `PATIENT_PATHOLOGY`; se exponen aqui por
        comodidad de lectura, sin crear ninguna estructura paralela.
        """
        return PatientPathologySerializer(obj.patient.pathologies.all(), many=True).data
