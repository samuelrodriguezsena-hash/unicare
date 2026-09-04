"""Reglas de negocio de patologias y de su asociacion a pacientes."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from apps.core.exceptions import ConflictError
from apps.people.models import Patient, PatientPathology

# Nombres de las restricciones del DER, para traducir el error de PostgreSQL a
# un mensaje que le sirva a quien llama la API.
_UQ_PATIENT_PATHOLOGY = "uq_patient_pathology"
_UQ_PRIMARY = "uq_patient_primary_pathology"


class PathologyService:
    """Asociacion paciente-patologia sobre `PATIENT_PATHOLOGY`."""

    @staticmethod
    def _traducir(exc: IntegrityError) -> ConflictError:
        detalle = str(exc)
        if _UQ_PRIMARY in detalle:
            return ConflictError(
                "El paciente ya tiene una patologia principal. "
                "Desmarca la actual antes de designar otra."
            )
        if _UQ_PATIENT_PATHOLOGY in detalle:
            return ConflictError("El paciente ya tiene asociada esa patologia.")
        return ConflictError("La operacion entra en conflicto con el estado actual.")

    @classmethod
    @transaction.atomic
    def attach(cls, paciente: Patient, datos: dict[str, Any]) -> PatientPathology:
        """Asocia una patologia al paciente.

        Las dos reglas que se pueden violar estan declaradas en el DER y las
        impone PostgreSQL, no este codigo:

          * `uq_patient_pathology`         no duplicar patologia por paciente;
          * `uq_patient_primary_pathology` maximo una principal por paciente.
        """
        try:
            return PatientPathology.objects.create(patient=paciente, **datos)
        except IntegrityError as exc:
            raise cls._traducir(exc) from exc

    @classmethod
    @transaction.atomic
    def update(
        cls, asociacion: PatientPathology, datos: dict[str, Any]
    ) -> PatientPathology:
        for campo, valor in datos.items():
            setattr(asociacion, campo, valor)
        try:
            asociacion.save()
        except IntegrityError as exc:
            raise cls._traducir(exc) from exc
        return asociacion

    @staticmethod
    def detach(asociacion: PatientPathology) -> None:
        """Desasocia una patologia.

        Es un borrado fisico legitimo: `PATIENT_PATHOLOGY` no define ningun
        campo de estado, y la operacion queda registrada en `AUDIT_LOG`.
        """
        asociacion.delete()
