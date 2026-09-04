"""Rutas de `massive_load`."""

from __future__ import annotations

from django.urls import path

from apps.massive_load.views import (
    ImportBatchDetailView,
    ImportBatchListCreateView,
    ImportBatchReportView,
    ImportBatchRowListView,
)

app_name = "massive_load"

urlpatterns = [
    path(
        "import-batches/",
        ImportBatchListCreateView.as_view(),
        name="import-batch-list",
    ),
    path(
        "import-batches/<int:import_batch_id>/",
        ImportBatchDetailView.as_view(),
        name="import-batch-detail",
    ),
    path(
        "import-batches/<int:import_batch_id>/rows/",
        ImportBatchRowListView.as_view(),
        name="import-batch-row-list",
    ),
    path(
        "import-batches/<int:import_batch_id>/report/",
        ImportBatchReportView.as_view(),
        name="import-batch-report",
    ),
]
