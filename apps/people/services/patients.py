"""Reglas de negocio de pacientes e historial clinico."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet

from apps.core.exceptions import ConflictError
from apps.people.models import (
    ClinicalHistory,
    ClinicalHistoryEntry,
    Note,
    Patient,
    PatientPathology,
)


class PatientService:
    """Alta, modificacion y baja logica de pacientes."""

    @staticmethod
    def base_queryset() -> QuerySet[Patient]:
        """Consulta de listado, con la patologia principal ya resuelta.

        El `Prefetch` acotado a `is_primary` evita el N+1 que produciria
        calcular la patologia principal fila a fila, y ademas evita traer
        todas las patologias de cada paciente solo para descartarlas.
        """
        primarias = PatientPathology.objects.filter(is_primary=True).select_related(
            "pathology"
        )
        return Patient.objects.prefetch_related(
            Prefetch("pathologies", queryset=primarias, to_attr="primarias")
        )

    @staticmethod
    @transaction.atomic
    def create(datos: dict[str, Any]) -> Patient:
        """Crea un paciente junto a su historial clinico.

        La documentacion exige que "cada paciente debe tener su historial
        clinico". El DER lo modela 1:1 obligatorio desde `CLINICAL_HISTORY`, asi
        que se crean juntos y de forma atomica: un paciente sin historial seria
        un estado invalido segun el contrato.
        """
        try:
            paciente = Patient.objects.create(**datos)
        except IntegrityError as exc:
            raise ConflictError(
                "Ya existe un paciente con ese numero de identificacion."
            ) from exc

        ClinicalHistory.objects.create(patient=paciente)
        return paciente

    @staticmethod
    @transaction.atomic
    def update(paciente: Patient, datos: dict[str, Any]) -> Patient:
        for campo, valor in datos.items():
            setattr(paciente, campo, valor)
        try:
            paciente.save()
        except IntegrityError as exc:
            raise ConflictError(
                "Ya existe un paciente con ese numero de identificacion."
            ) from exc
        return paciente

    @staticmethod
    def deactivate(paciente: Patient) -> Patient:
        """Baja LOGICA. El DER define `is_active`, asi que nunca se borra.

        Es idempotente: desactivar un paciente ya inactivo no es un error.
        """
        if paciente.is_active:
            paciente.is_active = False
            paciente.save(update_fields=["is_active", "updated_at", "updated_by"])
        return paciente

    @staticmethod
    def clinical_history(paciente: Patient) -> ClinicalHistory:
        """Historial del paciente, con entradas, notas y patologias resueltas.

        Se crea al vuelo si falta: los pacientes cargados masivamente o creados
        antes de esta version podrian no tenerlo.
        """
        historial = (
            ClinicalHistory.objects.filter(patient=paciente)
            .prefetch_related(
                Prefetch(
                    "entries",
                    queryset=ClinicalHistoryEntry.objects.order_by("-entry_date"),
                ),
                Prefetch("notes", queryset=Note.objects.order_by("-created_at")),
                Prefetch(
                    "patient__pathologies",
                    queryset=PatientPathology.objects.select_related("pathology"),
                ),
            )
            .first()
        )
        if historial is None:
            historial = ClinicalHistory.objects.create(patient=paciente)
        return historial
