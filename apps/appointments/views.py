"""Vistas de `appointments`.

Delgadas: validan, delegan en los servicios y devuelven. La logica de agenda,
priorizacion y calendario vive en `apps/appointments/services/`.
"""

from __future__ import annotations

import django_filters
from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListCreateAPIView, RetrieveUpdateAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.appointments.models import Appointment
from apps.appointments.serializers import (
    AppointmentPriorityConfirmSerializer,
    AppointmentReminderSerializer,
    AppointmentSerializer,
    AppointmentWriteSerializer,
    CalendarQuerySerializer,
)
from apps.appointments.services.appointments import AppointmentService
from apps.appointments.services.calendar import CalendarService
from apps.appointments.services.priority import AppointmentPriorityService
from apps.core.permissions import IsAuthenticatedAndActive


class AppointmentFilterSet(django_filters.FilterSet):
    scheduled_after = django_filters.IsoDateTimeFilter(
        field_name="scheduled_at", lookup_expr="gte"
    )
    scheduled_before = django_filters.IsoDateTimeFilter(
        field_name="scheduled_at", lookup_expr="lte"
    )

    class Meta:
        model = Appointment
        fields = ["patient", "status", "priority"]


class AppointmentListCreateView(ListCreateAPIView):
    """`GET/POST /api/v1/appointments/`.

    Al crear se solicita una prioridad sugerida por IA. Si la IA no responde,
    la cita se agenda igual: agendar es la operacion clinica, priorizar es
    apoyo.
    """

    permission_classes = [IsAuthenticatedAndActive]
    filterset_class = AppointmentFilterSet
    ordering_fields = ["scheduled_at", "created_at"]
    ordering = ["scheduled_at"]

    def get_queryset(self) -> QuerySet[Appointment]:
        return AppointmentService.base_queryset()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AppointmentWriteSerializer
        return AppointmentSerializer

    def create(self, request: Request, *args: object, **kwargs: object) -> Response:
        entrada = AppointmentWriteSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        cita = AppointmentService().create(entrada.validated_data)
        cita = self.get_queryset().get(pk=cita.pk)
        return Response(
            AppointmentSerializer(cita).data, status=status.HTTP_201_CREATED
        )


class AppointmentDetailView(RetrieveUpdateAPIView):
    """`GET/PATCH /api/v1/appointments/{id}/` - detalle y reprogramacion."""

    permission_classes = [IsAuthenticatedAndActive]
    lookup_field = "appointment_id"
    lookup_url_kwarg = "appointment_id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self) -> QuerySet[Appointment]:
        return AppointmentService.base_queryset()

    def get_serializer_class(self):
        # Siempre el de lectura: `partial_update` construye el de escritura por
        # su cuenta, y la metainformacion de OPTIONS solo inspecciona PUT/POST,
        # que esta vista no admite. Una rama para PATCH aqui seria inalcanzable.
        return AppointmentSerializer

    def partial_update(
        self, request: Request, *args: object, **kwargs: object
    ) -> Response:
        cita = self.get_object()
        entrada = AppointmentWriteSerializer(cita, data=request.data, partial=True)
        entrada.is_valid(raise_exception=True)
        cita = AppointmentService().update(cita, entrada.validated_data)
        return Response(AppointmentSerializer(cita).data)


class AppointmentCancelView(APIView):
    """`POST /api/v1/appointments/{id}/cancel/`."""

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, appointment_id: int) -> Response:
        cita = get_object_or_404(AppointmentService.base_queryset(), pk=appointment_id)
        cita = AppointmentService.cancel(cita)
        return Response(AppointmentSerializer(cita).data)


class AppointmentPriorityView(APIView):
    """`POST /api/v1/appointments/{id}/priority/`.

    Confirmacion PROFESIONAL de la prioridad. Es el paso de aprobacion del
    flujo: hasta que ocurre, `priority_final` esta vacio y la sugerencia de IA
    sigue pendiente de validacion.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def post(self, request: Request, appointment_id: int) -> Response:
        cita = get_object_or_404(AppointmentService.base_queryset(), pk=appointment_id)
        entrada = AppointmentPriorityConfirmSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        cita = AppointmentPriorityService.confirm(
            cita, entrada.validated_data["priority_final"]
        )
        return Response(AppointmentSerializer(cita).data)


class AppointmentReminderListView(APIView):
    """`GET /api/v1/appointments/{id}/reminders/`."""

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request, appointment_id: int) -> Response:
        cita = get_object_or_404(Appointment, pk=appointment_id)
        recordatorios = AppointmentService.reminders(cita)
        return Response(AppointmentReminderSerializer(recordatorios, many=True).data)


class AppointmentCalendarView(APIView):
    """`GET /api/v1/appointments/calendar/`.

    Representacion alternativa de las mismas citas, en el formato que esperan
    las librerias de calendario. No se anade nada al modelo para soportarla.
    """

    permission_classes = [IsAuthenticatedAndActive]

    def get(self, request: Request) -> Response:
        parametros = CalendarQuerySerializer(data=request.query_params)
        parametros.is_valid(raise_exception=True)
        datos = parametros.validated_data

        dia = datos.get("date") or timezone.localdate()
        inicio, fin = CalendarService.range_for(datos["view"], dia)

        citas = (
            Appointment.objects.select_related("patient")
            .filter(scheduled_at__gte=inicio, scheduled_at__lt=fin)
            .order_by("scheduled_at")
        )
        if "patient" in datos:
            citas = citas.filter(patient_id=datos["patient"])

        return Response(
            {
                "view": datos["view"],
                "start": inicio.isoformat(),
                "end": fin.isoformat(),
                "events": CalendarService.events(citas),
            }
        )
