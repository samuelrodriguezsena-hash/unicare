"""Serializers de `medications`.

Dos responsabilidades, ambas de validacion pura. Ninguna hace HTTP: la
comunicacion con la API externa vive en `services/farmacos_api.py`.

  * `FarmacoFilterSerializer`  valida los filtros que llegan por query string.
  * `FarmacoSerializer`        valida la respuesta de la API externa.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.medications.models import TreatmentPlan, TreatmentPlanMedication
from apps.people.models import PatientPathology

# Los cinco campos del contrato de la API externa. Se conservan con su
# capitalizacion original porque son a la vez los nombres de los query params
# aceptados y las claves de la respuesta.
FARMACO_FIELDS: tuple[str, ...] = (
    "Nombre_Medicamento",
    "Dosis_Comun",
    "Compuesto_Principal",
    "Patologia_Comun",
    "Familia_Farmaco",
)


class FarmacoFilterSerializer(serializers.Serializer):
    """Filtros admitidos por `GET /api/v1/farmacos/`.

    Los cinco son opcionales: cero o mas filtros. Cualquier otro query param se
    rechaza en la view con 400, para no dejar que el cliente controle
    arbitrariamente lo que se envia al servicio externo.

    Los valores no se normalizan (ni `strip`, ni cambio de mayusculas): la API
    externa hace coincidencia exacta y sensible a mayusculas, asi que alterarlos
    cambiaria el resultado de la busqueda.

    Un filtro presente pero vacio (`?Nombre_Medicamento=`) equivale a no
    enviarlo: DRF lo trata asi en query strings y es ademas lo seguro, porque
    reenviarlo pediria a la API externa una coincidencia con la cadena vacia.
    """

    Nombre_Medicamento = serializers.CharField(required=False)
    Dosis_Comun = serializers.CharField(required=False)
    Compuesto_Principal = serializers.CharField(required=False)
    Patologia_Comun = serializers.CharField(required=False)
    Familia_Farmaco = serializers.CharField(required=False)


class FarmacoSerializer(serializers.Serializer):
    """Contrato de un farmaco tal y como lo publica la API externa.

    Se usa para VALIDAR la respuesta entrante, no para serializar hacia fuera.
    Los cinco campos son obligatorios: si falta alguno, la respuesta no cumple
    el contrato documentado y se trata como error de integracion.

    `allow_blank=True` porque el contrato no prohibe valores vacios; lo que no
    se admite es que la clave no venga.
    """

    Nombre_Medicamento = serializers.CharField(allow_blank=True)
    Dosis_Comun = serializers.CharField(allow_blank=True)
    Compuesto_Principal = serializers.CharField(allow_blank=True)
    Patologia_Comun = serializers.CharField(allow_blank=True)
    Familia_Farmaco = serializers.CharField(allow_blank=True)


class TreatmentPlanMedicationSerializer(serializers.ModelSerializer):
    """Lectura de un medicamento asociado a un plan."""

    class Meta:
        model = TreatmentPlanMedication
        fields = (
            "treatment_plan_medication_id",
            "external_medication_id",
            "medication_name_snapshot",
            "medication_family_snapshot",
            "dose",
            "frequency",
            "duration",
            "route",
            "instructions",
            "validation_status",
            "warning_flag",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class TreatmentPlanMedicationWriteSerializer(serializers.ModelSerializer):
    """Alta de un medicamento en un plan.

    Los snapshots, `validation_status` y `warning_flag` NO son escribibles: los
    fija el servicio a partir de lo que responde la API externa. Si el cliente
    pudiera enviarlos, podria declarar como validado algo que no lo esta.
    """

    external_medication_id = serializers.CharField(max_length=100)

    class Meta:
        model = TreatmentPlanMedication
        fields = (
            "external_medication_id",
            "dose",
            "frequency",
            "duration",
            "route",
            "instructions",
        )


class TreatmentPlanMedicationUpdateSerializer(serializers.ModelSerializer):
    """Modificacion de posologia.

    `external_medication_id` queda fuera a proposito: cambiarlo invalidaria los
    snapshots y la validacion cruzada ya registrados.
    """

    class Meta:
        model = TreatmentPlanMedication
        fields = ("dose", "frequency", "duration", "route", "instructions")


class TreatmentPlanSerializer(serializers.ModelSerializer):
    """Lectura de un plan con sus medicamentos."""

    medications = TreatmentPlanMedicationSerializer(many=True, read_only=True)
    patient_name = serializers.SerializerMethodField()
    pathology_name = serializers.CharField(
        source="pathology.name", read_only=True, default=None
    )

    class Meta:
        model = TreatmentPlan
        fields = (
            "treatment_plan_id",
            "patient",
            "patient_name",
            "pathology",
            "pathology_name",
            "name",
            "start_date",
            "end_date",
            "status",
            "clinical_note",
            "medications",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def get_patient_name(self, obj: TreatmentPlan) -> str:
        return f"{obj.patient.first_name} {obj.patient.last_name}"


class TreatmentPlanWriteSerializer(serializers.ModelSerializer):
    """Alta y modificacion de un plan.

    `medications` es opcional: permite crear el plan con sus medicamentos en
    una sola operacion atomica, como exige la documentacion.
    """

    medications = TreatmentPlanMedicationWriteSerializer(
        many=True, required=False, write_only=True
    )

    class Meta:
        model = TreatmentPlan
        fields = (
            "patient",
            "pathology",
            "name",
            "start_date",
            "end_date",
            "status",
            "clinical_note",
            "medications",
        )

    def validate(self, attrs: dict) -> dict:
        inicio = attrs.get("start_date") or getattr(self.instance, "start_date", None)
        fin = attrs.get("end_date", getattr(self.instance, "end_date", None))
        if inicio and fin and fin < inicio:
            raise serializers.ValidationError(
                {"end_date": "La fecha de fin no puede ser anterior a la de inicio."}
            )
        return attrs


class TreatmentSuggestionRequestSerializer(serializers.Serializer):
    """Entrada de `POST /treatment-suggestions/`.

    Se parte de una patologia YA registrada en el historial del paciente, como
    exige la documentacion: no se aceptan nombres de patologia sueltos, que
    permitirian pedir sugerencias sobre cualquier cosa.
    """

    patient_pathology = serializers.PrimaryKeyRelatedField(
        queryset=PatientPathology.objects.select_related("pathology", "patient")
    )
