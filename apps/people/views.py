"""Vistas de `people`.

Delgadas por diseno: validan con el serializer, delegan en el servicio y
devuelven. Las reglas de negocio estan en `apps/people/services/`.

Todas heredan la politica de autenticacion global (JWT + usuario activo).
"""

from __future__ import annotations

from django.db.models import F, QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import (
    ListCreateAPIView,
    RetrieveUpdateAPIView,
)
from rest_framework.generics import (
    get_object_or_404 as drf_get_object_or_404,
)
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsAuthenticatedAndActive
from apps.people.filters import PatientFilterSet
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Note,
    Pathology,
    Patient,
    PatientPathology,
)
from apps.people.serializers import (
    ClinicalHistoryEntrySerializer,
    ClinicalHistorySerializer,
    NoteSerializer,
    PathologySerializer,
    PatientPathologySerializer,
    PatientSerializer,
    PatientWriteSerializer,
)
from apps.people.services.clinical_summary import ClinicalSummaryService
from apps.people.services.pathologies import PathologyService
from apps.people.services.patients import PatientService


class PatientListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/patients/`."""

    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = PatientFilterSet
    ordering_fields = ["last_name", "first_name", "created_at"]
    ordering = ["last_name", "first_name"]
    # `search` lo resuelve el FilterSet, no SearchFilter, para poder buscar en
    # nombre y apellido a la vez con un unico parametro.
    search_fields: list[str] = []

    def get_queryset(self) -> QuerySet[Patient]:
        return PatientService.base_queryset()

    def get_serializer_class(self):
        return (
            PatientWriteSerializer
            if self.request.method == "POST"
            else (PatientSerializer)
        )

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        entrada = PatientWriteSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        paciente = PatientService.create(entrada.validated_data)
        return Response(
            PatientSerializer(paciente).data, status=status.HTTP_201_CREATED
        )


class PatientDetailView(RetrieveUpdateAPIView):
    """`GET/PATCH /api/v1/patients/{id}/`.

    NO expone DELETE: el DER define `is_active` para dar de baja (A-09).
    """

    permission_classes = [IsAuthenticatedAndActive]
    lookup_field = "patient_id"
    lookup_url_kwarg = "patient_id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Patient]:
        return PatientService.base_queryset()

    def get_serializer_class(self):
        return (
            PatientWriteSerializer
            if self.request.method == "PATCH"
            else (PatientSerializer)
        )

    def partial_update(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        paciente = self.get_object()
        entrada = PatientWriteSerializer(paciente, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        paciente = PatientService.update(paciente, entrada.validated_data)
        return Response(PatientSerializer(paciente).data)


class PatientDeactivateView(APIView):
    """`POST /api/v1/patients/{id}/deactivate/` - baja logica."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, patient_id: int) -> Response:
        paciente = get_object_or_404(Patient, pk=patient_id)
        paciente = PatientService.deactivate(paciente)
        return Response(PatientSerializer(paciente).data)


class PatientClinicalHistoryView(APIView):
    """`GET /api/v1/patients/{id}/clinical-history/`."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request, patient_id: int) -> Response:
        paciente = get_object_or_404(Patient, pk=patient_id)
        historial = PatientService.clinical_history(paciente)
        return Response(ClinicalHistorySerializer(historial).data)


class PatientPathologyListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/patients/{id}/pathologies/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = PatientPathologySerializer
    pagination_class = None

    def get_paciente(self) -> Patient:
        return get_object_or_404(Patient, pk=self.kwargs["patient_id"])

    def get_queryset(self) -> QuerySet[PatientPathology]:
        """Primero la principal, luego el resto por nombre.

        `nulls_last` es imprescindible: el DER declara `is_primary` nullable
        (A-07) y PostgreSQL ordena los NULL PRIMERO en un `DESC`, con lo que
        las patologias sin marcar saldrian por encima de la principal.
        """
        return (
            PatientPathology.objects.filter(patient_id=self.kwargs["patient_id"])
            .select_related("pathology")
            .order_by(F("is_primary").desc(nulls_last=True), "pathology__name")
        )

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        paciente = self.get_paciente()
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        asociacion = PathologyService.attach(paciente, entrada.validated_data)
        return Response(
            PatientPathologySerializer(asociacion).data,
            status=status.HTTP_201_CREATED,
        )


class PatientPathologyDetailView(APIView):
    """`PATCH/DELETE /api/v1/patient-pathologies/{id}/`."""

    permission_classes = [IsAuthenticatedAndActive]

    def get_object(self, patient_pathology_id: int) -> PatientPathology:
        return drf_get_object_or_404(
            PatientPathology.objects.select_related("pathology"),
            pk=patient_pathology_id,
        )

    def patch(self, request: Request, patient_pathology_id: int) -> Response:
        asociacion = self.get_object(patient_pathology_id)
        entrada = PatientPathologySerializer(
            asociacion, data=request.data, partial=True
        )
        entrada.is_valid(raise_exception=True)
        asociacion = PathologyService.update(asociacion, entrada.validated_data)
        return Response(PatientPathologySerializer(asociacion).data)

    def delete(self, request: Request, patient_pathology_id: int) -> Response:
        PathologyService.detach(self.get_object(patient_pathology_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClinicalHistoryEntryListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/clinical-histories/{id}/entries/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = ClinicalHistoryEntrySerializer

    def get_historial(self) -> ClinicalHistory:
        return get_object_or_404(ClinicalHistory, pk=self.kwargs["clinical_history_id"])

    def get_queryset(self) -> QuerySet[ClinicalHistoryEntry]:
        return ClinicalHistoryEntry.objects.filter(
            clinical_history_id=self.kwargs["clinical_history_id"]
        ).order_by("-entry_date", "-clinical_history_entry_id")

    def perform_create(self, serializer: ClinicalHistoryEntrySerializer) -> None:
        serializer.save(clinical_history=self.get_historial())


class NoteListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/clinical-histories/{id}/notes/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = NoteSerializer

    def get_historial(self) -> ClinicalHistory:
        return get_object_or_404(ClinicalHistory, pk=self.kwargs["clinical_history_id"])

    def get_queryset(self) -> QuerySet[Note]:
        return Note.objects.filter(
            clinical_history_id=self.kwargs["clinical_history_id"]
        ).order_by("-created_at")

    def perform_create(self, serializer: NoteSerializer) -> None:
        serializer.save(clinical_history=self.get_historial())


class PathologyListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/pathologies/`."""

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = PathologySerializer
    queryset = Pathology.objects.order_by("name")
    filterset_fields = ["name"]
    ordering_fields = ["name", "created_at"]


class PathologyDetailView(RetrieveUpdateAPIView):
    """`GET/PATCH /api/v1/pathologies/{id}/`.

    Sin DELETE: `PATHOLOGY` no define campo de estado y esta referenciada desde
    planes de tratamiento e historiales (A-09).
    """

    permission_classes = [IsAuthenticatedAndActive]
    serializer_class = PathologySerializer
    queryset = Pathology.objects.all()
    lookup_field = "pathology_id"
    lookup_url_kwarg = "pathology_id"
    http_method_names = ["get", "patch", "head", "options"]


class PatientAISummaryView(APIView):
    """`POST /api/v1/patients/{id}/ai-summary/`.

    Genera un resumen narrativo del historial con Gemini y lo cachea en
    `CLINICAL_HISTORY.last_ai_summary`. La respuesta va siempre etiquetada como
    sugerencia de IA y pendiente de validacion profesional.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, patient_id: int) -> Response:
        paciente = get_object_or_404(Patient, pk=patient_id)
        resultado = ClinicalSummaryService().generate(paciente)
        return Response(resultado)
