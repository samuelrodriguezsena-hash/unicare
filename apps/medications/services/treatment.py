"""Reglas de negocio de planes de tratamiento.

Orquesta el DER con la API externa de farmacos. Aqui no hay HTTP: eso vive en
`farmacos_api.py`. Aqui esta lo que significa asociar un medicamento a un plan.

Dos puntos delicados, ambos documentados en docs/DECISIONS.md:

  * DEC-20: la API externa NO publica ningun campo identificador. Sus cinco
    campos son atributos, no claves. `external_medication_id` se interpreta
    como el `Nombre_Medicamento` publicado por esa API, que es el unico
    identificador natural disponible.

  * DEC-21: si la API externa no responde, NO se guarda el medicamento. Sin
    ella no hay snapshot ni validacion cruzada, y persistir informacion clinica
    sin validar seria peor que fallar.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import transaction

from apps.core.exceptions import DomainError
from apps.medications.choices import MedicationValidationStatus
from apps.medications.models import TreatmentPlan, TreatmentPlanMedication
from apps.medications.services.farmacos_api import FarmacosService

logger = logging.getLogger(__name__)


class MedicationNotFoundError(DomainError):
    """El medicamento indicado no existe en la fuente farmacologica externa."""

    status_code = 400
    default_detail = (
        "El medicamento no existe en el servicio de farmacos. "
        "Comprueba el nombre: la busqueda distingue mayusculas."
    )
    code = "medication_not_found"


def _normalizar(texto: str | None) -> str:
    """Normaliza para COMPARAR, nunca para almacenar."""
    return (texto or "").strip().casefold()


class TreatmentService:
    """Planes de tratamiento y sus medicamentos."""

    def __init__(self, farmacos: FarmacosService | None = None) -> None:
        self._farmacos = farmacos or FarmacosService()

    # ------------------------------------------------------------------
    # Planes
    # ------------------------------------------------------------------
    @transaction.atomic
    def create_plan(
        self, datos: dict[str, Any], medicamentos: list[dict[str, Any]] | None = None
    ) -> TreatmentPlan:
        """Crea un plan y, opcionalmente, sus medicamentos.

        Es atomico a proposito: un plan a medio poblar, con unos medicamentos
        si y otros no, seria un estado clinico enganoso. Si falla la asociacion
        de cualquiera, no se crea nada.
        """
        plan = TreatmentPlan.objects.create(**datos)
        for medicamento in medicamentos or []:
            self.add_medication(plan, medicamento)
        return plan

    @staticmethod
    @transaction.atomic
    def update_plan(plan: TreatmentPlan, datos: dict[str, Any]) -> TreatmentPlan:
        for campo, valor in datos.items():
            setattr(plan, campo, valor)
        plan.save()
        return plan

    # ------------------------------------------------------------------
    # Medicamentos del plan
    # ------------------------------------------------------------------
    def lookup_medication(self, external_medication_id: str) -> dict[str, Any]:
        """Recupera el farmaco de la fuente externa.

        La API filtra por coincidencia EXACTA y sensible a mayusculas, asi que
        el valor se envia tal cual llego, sin normalizar.
        """
        resultados = self._farmacos.list_farmacos(
            {"Nombre_Medicamento": external_medication_id}
        )
        if not resultados:
            raise MedicationNotFoundError
        return resultados[0]

    def cross_validate(
        self, plan: TreatmentPlan, farmaco: dict[str, Any]
    ) -> dict[str, Any]:
        """Compara la patologia habitual del farmaco con la del paciente.

        ESTO NO ES UNA VALIDACION CLINICA. Es una comparacion literal de
        nombres de patologia; ni interpreta, ni decide, ni sustituye el
        criterio profesional. Una discrepancia produce ADVERTENCIA y NUNCA
        bloquea la operacion.
        """
        del_farmaco = _normalizar(farmaco.get("Patologia_Comun"))

        patologias = {
            _normalizar(nombre)
            for nombre in plan.patient.pathologies.values_list(
                "pathology__name", flat=True
            )
        }
        if plan.pathology_id is not None:
            patologias.add(_normalizar(plan.pathology.name))
        patologias.discard("")

        if not del_farmaco or not patologias:
            # Sin datos que comparar no se afirma nada en ningun sentido.
            return {
                "status": MedicationValidationStatus.PENDING,
                "warning": False,
                "message": (
                    "No fue posible comparar la patologia del medicamento con "
                    "las del paciente: falta informacion."
                ),
            }

        if del_farmaco in patologias:
            return {
                "status": MedicationValidationStatus.VALIDATED,
                "warning": False,
                "message": None,
            }

        return {
            "status": MedicationValidationStatus.WARNING,
            "warning": True,
            "message": (
                "ADVERTENCIA: la patologia habitual de este medicamento "
                f"({farmaco.get('Patologia_Comun')}) no coincide con ninguna "
                "patologia registrada del paciente. Es una comparacion "
                "automatica de nombres, no una validacion clinica: requiere "
                "revision por un profesional."
            ),
        }

    @transaction.atomic
    def add_medication(
        self, plan: TreatmentPlan, datos: dict[str, Any]
    ) -> tuple[TreatmentPlanMedication, dict[str, Any]]:
        """Asocia un medicamento al plan, con snapshot y validacion cruzada.

        Devuelve el medicamento y el resultado de la validacion, que la vista
        expone aparte para que no se confunda con un dato clinico validado.
        """
        datos = dict(datos)
        external_id = datos.pop("external_medication_id")
        farmaco = self.lookup_medication(external_id)
        validacion = self.cross_validate(plan, farmaco)

        medicamento = TreatmentPlanMedication.objects.create(
            treatment_plan=plan,
            external_medication_id=external_id,
            # Snapshots desnormalizados: el DER los define para conservar lo que
            # la fuente externa decia en el momento de asociar el medicamento.
            medication_name_snapshot=farmaco.get("Nombre_Medicamento"),
            medication_family_snapshot=farmaco.get("Familia_Farmaco"),
            validation_status=validacion["status"],
            warning_flag=validacion["warning"],
            **datos,
        )
        return medicamento, validacion

    @staticmethod
    @transaction.atomic
    def update_medication(
        medicamento: TreatmentPlanMedication, datos: dict[str, Any]
    ) -> TreatmentPlanMedication:
        """Actualiza posologia. NO permite cambiar el medicamento.

        Cambiar `external_medication_id` invalidaria los snapshots y la
        validacion cruzada ya registrada; para eso se quita y se asocia otro.
        """
        for campo, valor in datos.items():
            setattr(medicamento, campo, valor)
        medicamento.save()
        return medicamento

    @staticmethod
    def remove_medication(medicamento: TreatmentPlanMedication) -> None:
        medicamento.delete()

    # ------------------------------------------------------------------
    # Alternativas farmacologicas
    # ------------------------------------------------------------------
    def alternatives(
        self, medicamento: TreatmentPlanMedication
    ) -> list[dict[str, Any]]:
        """Otros medicamentos de la misma familia, segun la fuente externa.

        Flujo exigido por la documentacion:
          1. obtener la informacion del medicamento desde la API externa;
          2. leer su `Familia_Farmaco`;
          3. buscar de nuevo por esa familia;
          4. excluir el propio medicamento.

        No se inventa informacion farmacologica local: si la familia no consta,
        no hay alternativas que ofrecer.
        """
        farmaco = self.lookup_medication(medicamento.external_medication_id)
        familia = farmaco.get("Familia_Farmaco")
        if not familia:
            return []

        de_la_familia = self._farmacos.list_farmacos({"Familia_Farmaco": familia})
        actual = _normalizar(farmaco.get("Nombre_Medicamento"))
        return [
            otro
            for otro in de_la_familia
            if _normalizar(otro.get("Nombre_Medicamento")) != actual
        ]
