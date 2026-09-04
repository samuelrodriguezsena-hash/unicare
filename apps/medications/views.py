"""Vistas de `medications`."""

from __future__ import annotations

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAuthenticatedAndActive
from apps.medications.models import TreatmentPlan, TreatmentPlanMedication
from apps.medications.serializers import (
    FarmacoFilterSerializer,
    TreatmentPlanMedicationSerializer,
    TreatmentPlanMedicationUpdateSerializer,
    TreatmentPlanMedicationWriteSerializer,
    TreatmentPlanSerializer,
    TreatmentPlanWriteSerializer,
    TreatmentSuggestionRequestSerializer,
)
from apps.medications.services.farmacos_api import FarmacosService
from apps.medications.services.suggestion import TreatmentSuggestionService
from apps.medications.services.treatment import TreatmentService


class FarmacoListView(APIView):
    """`GET /api/v1/farmacos/` - consulta la API externa de farmacos.

    El frontend nunca llama al servicio externo: lo hace este backend. La view
    valida los filtros, delega en `FarmacosService` y deja que
    `apps.core.exceptions.api_exception_handler` traduzca los errores de
    dominio a HTTP. Aqui no hay ni una linea de logica HTTP externa.

    Hereda la politica de autenticacion global del proyecto (JWT +
    `IsAuthenticated`); no la modifica ni la relaja. El JWT del usuario NO se
    reenvia al servicio externo: el cliente HTTP construye sus propias
    cabeceras.
    """

    def get(self, request: Request) -> Response:
        filters = self._validated_filters(request)
        farmacos = FarmacosService().list_farmacos(filters)
        return Response(farmacos)

    @staticmethod
    def _validated_filters(request: Request) -> dict[str, str]:
        """Valida la query string y devuelve solo los filtros permitidos.

        Un query param desconocido se rechaza con 400 en lugar de ignorarse: el
        cliente no debe poder inyectar parametros arbitrarios en la peticion al
        servicio externo, y un filtro mal escrito devolveria silenciosamente
        resultados de mas.
        """
        serializer = FarmacoFilterSerializer(data=request.query_params)
        desconocidos = set(request.query_params) - set(serializer.fields)
        if desconocidos:
            raise ValidationError(
                dict.fromkeys(sorted(desconocidos), "Filtro no admitido.")
            )

        serializer.is_valid(raise_exception=True)
        return dict(serializer.validated_data)


class TreatmentPlanListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/treatment-plans/`.

    El alta es atomica: si falla la asociacion de cualquier medicamento, no se
    crea el plan. Un plan a medio poblar seria clinicamente enganoso.
    """

    permission_classes = [IsAuthenticatedAndActive]
    filterset_fields = ["patient", "pathology", "status"]
    ordering_fields = ["start_date", "created_at", "name"]
    ordering = ["-start_date"]

    def get_queryset(self) -> QuerySet[TreatmentPlan]:
        # select_related evita una consulta por plan para paciente y patologia;
        # prefetch_related, una por plan para sus medicamentos.
        return (
            TreatmentPlan.objects.select_related("patient", "pathology")
            .prefetch_related("medications")
            .all()
        )

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TreatmentPlanWriteSerializer
        return TreatmentPlanSerializer

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        entrada = TreatmentPlanWriteSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        medicamentos = datos.pop("medications", [])

        plan = TreatmentService().create_plan(datos, medicamentos)
        plan = self.get_queryset().get(pk=plan.pk)
        return Response(
            TreatmentPlanSerializer(plan).data, status=status.HTTP_201_CREATED
        )


class TreatmentPlanDetailView(RetrieveUpdateAPIView):
    """`GET/PATCH /api/v1/treatment-plans/{id}/`."""

    permission_classes = [IsAuthenticatedAndActive]
    lookup_field = "treatment_plan_id"
    lookup_url_kwarg = "treatment_plan_id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[TreatmentPlan]:
        return TreatmentPlan.objects.select_related(
            "patient", "pathology"
        ).prefetch_related("medications")

    def get_serializer_class(self):
        # Siempre el de lectura: `partial_update` construye el de escritura por
        # su cuenta, y la metainformacion de OPTIONS solo inspecciona PUT/POST,
        # que esta vista no admite. Una rama para PATCH aqui seria inalcanzable.
        return TreatmentPlanSerializer

    def partial_update(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        plan = self.get_object()
        entrada = TreatmentPlanWriteSerializer(plan, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        datos = dict(entrada.validated_data)
        # Los medicamentos no se sustituyen en bloque: se gestionan por su
        # propio endpoint, para que cada alta pase por la validacion cruzada.
        datos.pop("medications", None)
        plan = TreatmentService().update_plan(plan, datos)
        return Response(TreatmentPlanSerializer(plan).data)


class TreatmentPlanMedicationListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/treatment-plans/{id}/medications/`.

    El alta consulta la API externa de farmacos, guarda los snapshots y ejecuta
    la validacion cruzada. Una discrepancia NO bloquea: se devuelve como
    advertencia, claramente separada del recurso creado.
    """

    permission_classes = [IsAuthenticatedAndActive]
    pagination_class = None

    def get_plan(self) -> TreatmentPlan:
        return get_object_or_404(
            TreatmentPlan.objects.select_related("patient", "pathology"),
            pk=self.kwargs["treatment_plan_id"],
        )

    def get_queryset(self) -> QuerySet[TreatmentPlanMedication]:
        return TreatmentPlanMedication.objects.filter(
            treatment_plan_id=self.kwargs["treatment_plan_id"]
        ).order_by("treatment_plan_medication_id")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return TreatmentPlanMedicationWriteSerializer
        return TreatmentPlanMedicationSerializer

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        plan = self.get_plan()
        entrada = TreatmentPlanMedicationWriteSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        medicamento, validacion = TreatmentService().add_medication(
            plan, entrada.validated_data
        )
        cuerpo = TreatmentPlanMedicationSerializer(medicamento).data
        # La validacion viaja aparte del recurso: es una advertencia
        # automatica, no un atributo clinico del medicamento.
        cuerpo["validation"] = validacion
        return Response(cuerpo, status=status.HTTP_201_CREATED)


class TreatmentPlanMedicationDetailView(APIView):
    """`PATCH/DELETE /api/v1/treatment-plan-medications/{id}/`."""

    permission_classes = [IsAuthenticatedAndActive]

    def get_object(self, treatment_plan_medication_id: int) -> TreatmentPlanMedication:
        return get_object_or_404(
            TreatmentPlanMedication, pk=treatment_plan_medication_id
        )

    def patch(self, request: Request, treatment_plan_medication_id: int) -> Response:
        medicamento = self.get_object(treatment_plan_medication_id)
        entrada = TreatmentPlanMedicationUpdateSerializer(
            medicamento, data=request.data, partial=True
        )
        entrada.is_valid(raise_exception=True)
        medicamento = TreatmentService().update_medication(
            medicamento, entrada.validated_data
        )
        return Response(TreatmentPlanMedicationSerializer(medicamento).data)

    def delete(self, request: Request, treatment_plan_medication_id: int) -> Response:
        TreatmentService().remove_medication(
            self.get_object(treatment_plan_medication_id)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class TreatmentPlanMedicationAlternativesView(APIView):
    """`GET /api/v1/treatment-plan-medications/{id}/alternatives/`.

    Devuelve medicamentos de la misma `Familia_Farmaco` segun la API externa,
    excluido el actual. No se inventa informacion farmacologica local.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request, treatment_plan_medication_id: int) -> Response:
        medicamento = get_object_or_404(
            TreatmentPlanMedication, pk=treatment_plan_medication_id
        )
        alternativas = TreatmentService().alternatives(medicamento)
        return Response(
            {
                "external_medication_id": medicamento.external_medication_id,
                "family": medicamento.medication_family_snapshot,
                "alternatives": alternativas,
            }
        )


class TreatmentSuggestionView(APIView):
    """`POST /api/v1/treatment-suggestions/`.

    Sugerencia de familias farmacologicas y principios activos para una
    patologia del historial del paciente.

    NO persiste nada (C-06 / DEC-07): el DER no define donde guardar la
    sugerencia ni su estado de aprobacion, y no se crean tablas arbitrarias. El
    acto de aprobacion es crear un `TREATMENT_PLAN_MEDICATION` a partir de ella.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request) -> Response:
        entrada = TreatmentSuggestionRequestSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        asociacion = entrada.validated_data["patient_pathology"]
        return Response(TreatmentSuggestionService().suggest(asociacion))
