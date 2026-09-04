"""Rutas de `medications`."""

from __future__ import annotations

from django.urls import path

from apps.medications.views import (
    FarmacoListView,
    TreatmentPlanDetailView,
    TreatmentPlanListCreateView,
    TreatmentPlanMedicationAlternativesView,
    TreatmentPlanMedicationDetailView,
    TreatmentPlanMedicationListCreateView,
    TreatmentSuggestionView,
)

app_name = "medications"

urlpatterns = [
    path("farmacos/", FarmacoListView.as_view(), name="farmaco-list"),
    path(
        "treatment-suggestions/",
        TreatmentSuggestionView.as_view(),
        name="treatment-suggestion",
    ),
    path(
        "treatment-plans/",
        TreatmentPlanListCreateView.as_view(),
        name="treatment-plan-list",
    ),
    path(
        "treatment-plans/<int:treatment_plan_id>/",
        TreatmentPlanDetailView.as_view(),
        name="treatment-plan-detail",
    ),
    path(
        "treatment-plans/<int:treatment_plan_id>/medications/",
        TreatmentPlanMedicationListCreateView.as_view(),
        name="treatment-plan-medication-list",
    ),
    # `alternatives/` va antes que el detalle para que no lo capture.
    path(
        "treatment-plan-medications/<int:treatment_plan_medication_id>/alternatives/",
        TreatmentPlanMedicationAlternativesView.as_view(),
        name="treatment-plan-medication-alternatives",
    ),
    path(
        "treatment-plan-medications/<int:treatment_plan_medication_id>/",
        TreatmentPlanMedicationDetailView.as_view(),
        name="treatment-plan-medication-detail",
    ),
]
