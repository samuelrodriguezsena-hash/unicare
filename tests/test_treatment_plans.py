"""Tests de planes de tratamiento (FASE 8).

Ninguna llamada real a la API externa: `respx` intercepta el transporte de
httpx. Requiere PostgreSQL porque se verifica lo que queda persistido.
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import respx
from rest_framework.test import APIClient

from apps.core.models import AuditLog, User
from apps.medications.choices import MedicationValidationStatus
from apps.medications.models import TreatmentPlan, TreatmentPlanMedication
from apps.medications.services import farmacos_api
from apps.people.models import Pathology, Patient, PatientPathology
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

PLANES = "/api/v1/treatment-plans/"
EXTERNAL_URL = "https://farmacos.invalid/v1/farmacos"

ATORVASTATINA = {
    "Nombre_Medicamento": "Atorvastatina",
    "Dosis_Comun": "20 mg",
    "Compuesto_Principal": "Atorvastatina",
    "Patologia_Comun": "Colesterol Alto",
    "Familia_Farmaco": "Estatinas",
}
SIMVASTATINA = {
    "Nombre_Medicamento": "Simvastatina",
    "Dosis_Comun": "40 mg",
    "Compuesto_Principal": "Simvastatina",
    "Patologia_Comun": "Colesterol Alto",
    "Familia_Farmaco": "Estatinas",
}


@pytest.fixture(autouse=True)
def _reset_http_client():
    farmacos_api.reset_client()
    yield
    farmacos_api.reset_client()


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def client(clinico: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=clinico)
    return api


@pytest.fixture
def colesterol() -> Pathology:
    return Pathology.objects.create(name="Colesterol Alto")


@pytest.fixture
def paciente(colesterol: Pathology) -> Patient:
    paciente = Patient.objects.create(
        identification_number="1098765432", first_name="Ana", last_name="Gomez"
    )
    PatientPathology.objects.create(
        patient=paciente, pathology=colesterol, is_primary=True
    )
    return paciente


@pytest.fixture
def datos_plan(paciente: Patient, colesterol: Pathology) -> dict:
    return {
        "patient": paciente.pk,
        "pathology": colesterol.pk,
        "name": "Manejo de dislipidemia",
        "start_date": str(date.today()),
        "status": "ACTIVE",
    }


@pytest.fixture
def plan(client: APIClient, datos_plan: dict) -> dict:
    return client.post(PLANES, datos_plan, format="json").json()


def ruta_busqueda(resultados: list[dict]) -> respx.Route:
    return respx.get(EXTERNAL_URL).mock(
        return_value=httpx.Response(200, json=resultados)
    )


class TestPlanes:
    def test_crea_un_plan(self, client: APIClient, datos_plan: dict) -> None:
        respuesta = client.post(PLANES, datos_plan, format="json")
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["name"] == "Manejo de dislipidemia"
        assert cuerpo["patient_name"] == "Ana Gomez"
        assert cuerpo["pathology_name"] == "Colesterol Alto"
        assert cuerpo["medications"] == []

    def test_la_patologia_es_opcional(
        self, client: APIClient, datos_plan: dict
    ) -> None:
        # A-05: el DER declara `pathology_id` como FK nullable.
        del datos_plan["pathology"]
        respuesta = client.post(PLANES, datos_plan, format="json")
        assert respuesta.status_code == 201
        assert respuesta.json()["pathology"] is None

    def test_rechaza_una_fecha_de_fin_anterior_al_inicio(
        self, client: APIClient, datos_plan: dict
    ) -> None:
        datos_plan["end_date"] = str(date.today() - timedelta(days=1))
        respuesta = client.post(PLANES, datos_plan, format="json")
        assert respuesta.status_code == 400
        assert "end_date" in respuesta.json()

    def test_rechaza_un_estado_fuera_del_enum(
        self, client: APIClient, datos_plan: dict
    ) -> None:
        datos_plan["status"] = "INVENTADO"
        assert client.post(PLANES, datos_plan, format="json").status_code == 400

    def test_detalle_y_modificacion(self, client: APIClient, plan: dict) -> None:
        url = f"{PLANES}{plan['treatment_plan_id']}/"
        assert client.get(url).status_code == 200

        respuesta = client.patch(url, {"status": "COMPLETED"}, format="json")
        assert respuesta.status_code == 200
        assert respuesta.json()["status"] == "COMPLETED"

    def test_filtros(self, client: APIClient, plan: dict, paciente: Patient) -> None:
        assert client.get(PLANES, {"patient": paciente.pk}).json()["count"] == 1
        assert client.get(PLANES, {"status": "ACTIVE"}).json()["count"] == 1
        assert client.get(PLANES, {"status": "CANCELLED"}).json()["count"] == 0

    def test_no_expone_borrado(self, client: APIClient, plan: dict) -> None:
        respuesta = client.delete(f"{PLANES}{plan['treatment_plan_id']}/")
        assert respuesta.status_code == 405


class TestAltaAtomicaConMedicamentos:
    @respx.mock
    def test_crea_el_plan_con_sus_medicamentos(
        self, client: APIClient, datos_plan: dict
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        datos_plan["medications"] = [
            {"external_medication_id": "Atorvastatina", "dose": "20 mg"}
        ]

        respuesta = client.post(PLANES, datos_plan, format="json")
        assert respuesta.status_code == 201
        medicamentos = respuesta.json()["medications"]
        assert len(medicamentos) == 1
        assert medicamentos[0]["medication_name_snapshot"] == "Atorvastatina"

    @respx.mock
    def test_si_falla_un_medicamento_no_se_crea_el_plan(
        self, client: APIClient, datos_plan: dict
    ) -> None:
        # Un plan a medio poblar seria clinicamente enganoso.
        ruta_busqueda([])
        datos_plan["medications"] = [
            {"external_medication_id": "Inexistente", "dose": "10 mg"}
        ]

        respuesta = client.post(PLANES, datos_plan, format="json")
        assert respuesta.status_code == 400
        assert TreatmentPlan.objects.count() == 0


class TestAsociarMedicamentos:
    @respx.mock
    def test_guarda_los_snapshots_de_la_fuente_externa(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina", "dose": "20 mg"},
            format="json",
        )

        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["medication_name_snapshot"] == "Atorvastatina"
        assert cuerpo["medication_family_snapshot"] == "Estatinas"
        assert cuerpo["dose"] == "20 mg"

    @respx.mock
    def test_consulta_la_api_externa_por_nombre_exacto(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta = ruta_busqueda([ATORVASTATINA])
        client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )
        params = ruta.calls.last.request.url.params
        assert params["Nombre_Medicamento"] == "Atorvastatina"

    @respx.mock
    def test_un_medicamento_inexistente_devuelve_400(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "NoExiste"},
            format="json",
        )
        assert respuesta.status_code == 400
        assert respuesta.json()["code"] == "medication_not_found"
        assert TreatmentPlanMedication.objects.count() == 0

    @respx.mock
    def test_si_la_api_externa_falla_no_se_guarda_nada(
        self, client: APIClient, plan: dict
    ) -> None:
        # DEC-21: sin la fuente externa no hay snapshot ni validacion cruzada.
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(500))
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )
        assert respuesta.status_code == 502
        assert TreatmentPlanMedication.objects.count() == 0

    @respx.mock
    def test_el_cliente_no_puede_declarar_un_medicamento_como_validado(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {
                "external_medication_id": "Atorvastatina",
                "validation_status": "VALIDATED",
                "warning_flag": False,
                "medication_family_snapshot": "Inventada",
            },
            format="json",
        )
        # Los tres campos los fija el servicio, no la entrada.
        assert respuesta.json()["medication_family_snapshot"] == "Estatinas"

    @respx.mock
    def test_lista_los_medicamentos_del_plan(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        url = f"{PLANES}{plan['treatment_plan_id']}/medications/"
        client.post(url, {"external_medication_id": "Atorvastatina"}, format="json")

        assert len(client.get(url).json()) == 1


class TestValidacionCruzada:
    @respx.mock
    def test_sin_discrepancia_queda_validado(
        self, client: APIClient, plan: dict
    ) -> None:
        # El paciente tiene "Colesterol Alto", igual que el farmaco.
        ruta_busqueda([ATORVASTATINA])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )

        cuerpo = respuesta.json()
        assert cuerpo["validation_status"] == MedicationValidationStatus.VALIDATED
        assert cuerpo["warning_flag"] is False
        assert cuerpo["validation"]["message"] is None

    @respx.mock
    def test_con_discrepancia_advierte_pero_NO_bloquea(
        self, client: APIClient, plan: dict
    ) -> None:
        farmaco = {**ATORVASTATINA, "Patologia_Comun": "Diabetes Tipo 2"}
        ruta_busqueda([farmaco])

        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )

        # La documentacion es explicita: advertir, no bloquear.
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["validation_status"] == MedicationValidationStatus.WARNING
        assert cuerpo["warning_flag"] is True
        assert "ADVERTENCIA" in cuerpo["validation"]["message"]
        assert TreatmentPlanMedication.objects.count() == 1

    @respx.mock
    def test_la_advertencia_se_separa_de_una_validacion_clinica(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([{**ATORVASTATINA, "Patologia_Comun": "Diabetes Tipo 2"}])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )
        mensaje = respuesta.json()["validation"]["message"]
        assert "no una validacion clinica" in mensaje
        assert "revision por un profesional" in mensaje

    @respx.mock
    def test_la_comparacion_ignora_mayusculas_y_espacios(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([{**ATORVASTATINA, "Patologia_Comun": "  colesterol ALTO "}])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )
        assert respuesta.json()["validation_status"] == (
            MedicationValidationStatus.VALIDATED
        )

    @respx.mock
    def test_sin_patologias_del_paciente_no_se_afirma_nada(
        self, client: APIClient, datos_plan: dict, paciente: Patient
    ) -> None:
        PatientPathology.objects.filter(patient=paciente).delete()
        del datos_plan["pathology"]
        plan = client.post(PLANES, datos_plan, format="json").json()

        ruta_busqueda([ATORVASTATINA])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )

        cuerpo = respuesta.json()
        assert cuerpo["validation_status"] == MedicationValidationStatus.PENDING
        assert cuerpo["warning_flag"] is False
        assert "falta informacion" in cuerpo["validation"]["message"]

    @respx.mock
    def test_tambien_compara_contra_la_patologia_del_plan(
        self, client: APIClient, datos_plan: dict, paciente: Patient
    ) -> None:
        # Sin patologias en el paciente, pero el plan si declara una.
        PatientPathology.objects.filter(patient=paciente).delete()
        plan = client.post(PLANES, datos_plan, format="json").json()

        ruta_busqueda([ATORVASTATINA])
        respuesta = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        )
        assert respuesta.json()["validation_status"] == (
            MedicationValidationStatus.VALIDATED
        )


class TestAlternativas:
    @pytest.fixture
    def medicamento(self, client: APIClient, plan: dict) -> dict:
        with respx.mock:
            ruta_busqueda([ATORVASTATINA])
            return client.post(
                f"{PLANES}{plan['treatment_plan_id']}/medications/",
                {"external_medication_id": "Atorvastatina"},
                format="json",
            ).json()

    @respx.mock
    def test_devuelve_la_misma_familia_excluyendo_el_actual(
        self, client: APIClient, medicamento: dict
    ) -> None:
        respx.get(EXTERNAL_URL).mock(
            side_effect=[
                httpx.Response(200, json=[ATORVASTATINA]),
                httpx.Response(200, json=[ATORVASTATINA, SIMVASTATINA]),
            ]
        )
        url = (
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/alternatives/"
        )
        respuesta = client.get(url)

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["family"] == "Estatinas"
        nombres = [a["Nombre_Medicamento"] for a in cuerpo["alternatives"]]
        assert nombres == ["Simvastatina"]

    @respx.mock
    def test_busca_por_la_familia_del_farmaco(
        self, client: APIClient, medicamento: dict
    ) -> None:
        ruta = respx.get(EXTERNAL_URL).mock(
            side_effect=[
                httpx.Response(200, json=[ATORVASTATINA]),
                httpx.Response(200, json=[]),
            ]
        )
        client.get(
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/alternatives/"
        )
        assert ruta.calls.last.request.url.params["Familia_Farmaco"] == "Estatinas"

    @respx.mock
    def test_sin_familia_no_hay_alternativas_que_ofrecer(
        self, client: APIClient, medicamento: dict
    ) -> None:
        # No se inventa informacion farmacologica local.
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(
                200, json=[{**ATORVASTATINA, "Familia_Farmaco": ""}]
            )
        )
        respuesta = client.get(
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/alternatives/"
        )
        assert respuesta.json()["alternatives"] == []


class TestModificarYQuitarMedicamentos:
    @pytest.fixture
    def medicamento(self, client: APIClient, plan: dict) -> dict:
        with respx.mock:
            ruta_busqueda([ATORVASTATINA])
            return client.post(
                f"{PLANES}{plan['treatment_plan_id']}/medications/",
                {"external_medication_id": "Atorvastatina", "dose": "20 mg"},
                format="json",
            ).json()

    def test_modifica_la_posologia(self, client: APIClient, medicamento: dict) -> None:
        url = (
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/"
        )
        respuesta = client.patch(
            url, {"dose": "40 mg", "frequency": "cada 24 h"}, format="json"
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["dose"] == "40 mg"

    def test_no_permite_cambiar_el_medicamento(
        self, client: APIClient, medicamento: dict
    ) -> None:
        # Cambiarlo invalidaria los snapshots y la validacion ya registrada.
        url = (
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/"
        )
        respuesta = client.patch(
            url, {"external_medication_id": "Simvastatina"}, format="json"
        )
        assert respuesta.json()["external_medication_id"] == "Atorvastatina"

    def test_quita_un_medicamento(self, client: APIClient, medicamento: dict) -> None:
        url = (
            "/api/v1/treatment-plan-medications/"
            f"{medicamento['treatment_plan_medication_id']}/"
        )
        assert client.delete(url).status_code == 204
        assert client.delete(url).status_code == 404


class TestSinCatalogoLocal:
    def test_medications_solo_tiene_las_dos_tablas_del_der(self) -> None:
        """La API externa es la unica fuente farmacologica.

        Si alguien anadiera un catalogo local de farmacos, aparecerian tablas
        de mas en esta app.
        """
        from django.apps import apps

        tablas = {
            modelo._meta.db_table
            for modelo in apps.get_app_config("medications").get_models()
        }
        assert tablas == {"treatment_plan", "treatment_plan_medication"}

    def test_el_medicamento_se_referencia_por_id_externo(self) -> None:
        campo = TreatmentPlanMedication._meta.get_field("external_medication_id")
        assert campo.is_relation is False


class TestSeguridadYAuditoria:
    def test_un_anonimo_no_puede_operar(self) -> None:
        assert APIClient().get(PLANES).status_code == 401

    def test_el_alta_del_plan_queda_auditada(
        self, client: APIClient, clinico: User, plan: dict
    ) -> None:
        registro = AuditLog.objects.get(
            entity_type="treatment_plan",
            entity_id=plan["treatment_plan_id"],
            action="CREATE",
        )
        assert registro.user_id == clinico.pk

    @respx.mock
    def test_asociar_un_medicamento_queda_auditado(
        self, client: APIClient, plan: dict
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        creado = client.post(
            f"{PLANES}{plan['treatment_plan_id']}/medications/",
            {"external_medication_id": "Atorvastatina"},
            format="json",
        ).json()

        assert AuditLog.objects.filter(
            entity_type="treatment_plan_medication",
            entity_id=creado["treatment_plan_medication_id"],
            action="CREATE",
        ).exists()


class TestRendimiento:
    @respx.mock
    def test_el_listado_no_incurre_en_n_mas_1(
        self, client: APIClient, datos_plan: dict, django_assert_max_num_queries
    ) -> None:
        ruta_busqueda([ATORVASTATINA])
        for i in range(5):
            client.post(
                PLANES,
                {
                    **datos_plan,
                    "name": f"Plan {i}",
                    "medications": [{"external_medication_id": "Atorvastatina"}],
                },
                format="json",
            )

        # Conteo + planes + prefetch de medicamentos.
        with django_assert_max_num_queries(4):
            client.get(PLANES)


class TestDescripcionDeLaApi:
    """`OPTIONS` debe describir los campos ESCRIBIBLES, no los de lectura.

    Es lo que consume un frontend para construir formularios: si anunciara los
    campos de solo lectura, ofreceria editar snapshots o el estado de
    validacion, que solo fija el servidor.
    """

    def test_options_del_listado_de_planes(self, client: APIClient) -> None:
        campos = client.options(PLANES).json()["actions"]["POST"]
        assert "name" in campos
        assert "medications" in campos
        assert "created_at" not in campos

    def test_options_del_detalle_de_un_plan(
        self, client: APIClient, plan: dict
    ) -> None:
        respuesta = client.options(f"{PLANES}{plan['treatment_plan_id']}/")
        assert respuesta.status_code == 200

    def test_options_de_los_medicamentos_de_un_plan(
        self, client: APIClient, plan: dict
    ) -> None:
        campos = client.options(
            f"{PLANES}{plan['treatment_plan_id']}/medications/"
        ).json()["actions"]["POST"]
        assert "external_medication_id" in campos
        # Nunca ofrecer como editables los campos que fija el servidor.
        assert "validation_status" not in campos
        assert "warning_flag" not in campos
        assert "medication_name_snapshot" not in campos
