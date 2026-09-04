"""Ruteo raiz de UniCare.

Toda la API vive bajo /api/v1/. Las rutas de dominio se incorporan en sus
fases correspondientes.
"""

from __future__ import annotations

from django.urls import include, path

urlpatterns = [
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.people.urls")),
    path("api/v1/", include("apps.medications.urls")),
    path("api/v1/", include("apps.appointments.urls")),
    path("api/v1/", include("apps.massive_load.urls")),
]
