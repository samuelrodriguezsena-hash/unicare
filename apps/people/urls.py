"""Rutas de `people`."""

from __future__ import annotations

from django.urls import path

from apps.people.views import (
    ClinicalHistoryEntryListCreateView,
    NoteListCreateView,
    PathologyDetailView,
    PathologyListCreateView,
    PatientAISummaryView,
    PatientClinicalHistoryView,
    PatientDeactivateView,
    PatientDetailView,
    PatientListCreateView,
    PatientPathologyDetailView,
    PatientPathologyListCreateView,
)

app_name = "people"

urlpatterns = [
    path("patients/", PatientListCreateView.as_view(), name="patient-list"),
    path(
        "patients/<int:patient_id>/",
        PatientDetailView.as_view(),
        name="patient-detail",
    ),
    path(
        "patients/<int:patient_id>/deactivate/",
        PatientDeactivateView.as_view(),
        name="patient-deactivate",
    ),
    path(
        "patients/<int:patient_id>/clinical-history/",
        PatientClinicalHistoryView.as_view(),
        name="patient-clinical-history",
    ),
    path(
        "patients/<int:patient_id>/ai-summary/",
        PatientAISummaryView.as_view(),
        name="patient-ai-summary",
    ),
    path(
        "patients/<int:patient_id>/pathologies/",
        PatientPathologyListCreateView.as_view(),
        name="patient-pathology-list",
    ),
    path(
        "patient-pathologies/<int:patient_pathology_id>/",
        PatientPathologyDetailView.as_view(),
        name="patient-pathology-detail",
    ),
    path(
        "clinical-histories/<int:clinical_history_id>/entries/",
        ClinicalHistoryEntryListCreateView.as_view(),
        name="clinical-history-entry-list",
    ),
    path(
        "clinical-histories/<int:clinical_history_id>/notes/",
        NoteListCreateView.as_view(),
        name="clinical-history-note-list",
    ),
    path("pathologies/", PathologyListCreateView.as_view(), name="pathology-list"),
    path(
        "pathologies/<int:pathology_id>/",
        PathologyDetailView.as_view(),
        name="pathology-detail",
    ),
]
