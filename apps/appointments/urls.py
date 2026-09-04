"""Rutas de `appointments`."""

from __future__ import annotations

from django.urls import path

from apps.appointments.views import (
    AppointmentCalendarView,
    AppointmentCancelView,
    AppointmentDetailView,
    AppointmentListCreateView,
    AppointmentPriorityView,
    AppointmentReminderListView,
)

app_name = "appointments"

urlpatterns = [
    # `calendar/` va antes que `<int:appointment_id>/` para que no lo capture.
    path(
        "appointments/calendar/",
        AppointmentCalendarView.as_view(),
        name="appointment-calendar",
    ),
    path(
        "appointments/",
        AppointmentListCreateView.as_view(),
        name="appointment-list",
    ),
    path(
        "appointments/<int:appointment_id>/",
        AppointmentDetailView.as_view(),
        name="appointment-detail",
    ),
    path(
        "appointments/<int:appointment_id>/cancel/",
        AppointmentCancelView.as_view(),
        name="appointment-cancel",
    ),
    path(
        "appointments/<int:appointment_id>/priority/",
        AppointmentPriorityView.as_view(),
        name="appointment-priority",
    ),
    path(
        "appointments/<int:appointment_id>/reminders/",
        AppointmentReminderListView.as_view(),
        name="appointment-reminder-list",
    ),
]
