"""Tests de la API de consulta y exportacion de auditoria (FASE 5)."""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.core.context import acting_as
from apps.core.models import AuditLog, User
from apps.core.permissions import describe_policy
from apps.people.models import Patient
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

LISTA = "/api/v1/audit-logs/"
EXPORT = "/api/v1/audit-logs/export/"


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def client(clinico: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=clinico)
    return api


@pytest.fixture
def paciente(clinico: User) -> Patient:
    with acting_as(clinico):
        paciente = Patient.objects.create(
            identification_number="1098765432", first_name="Ana", last_name="Gomez"
        )
        paciente.last_name = "Gomez Ruiz"
        paciente.save()
    return paciente


class TestPermisos:
    def test_un_anonimo_no_puede_consultar_la_auditoria(self) -> None:
        assert APIClient().get(LISTA).status_code == 401

    def test_un_usuario_inactivo_tampoco(self) -> None:
        inactivo = User.objects.create_user(username="baja", password="z" * 14)
        inactivo.is_active = False
        api = APIClient()
        api.force_authenticate(user=inactivo)
        assert api.get(LISTA).status_code == 403

    def test_la_auditoria_es_de_solo_lectura(self, client: APIClient) -> None:
        # No debe poder falsificarse un registro de auditoria por API.
        assert client.post(LISTA, {}, format="json").status_code in {403, 405}

    def test_la_politica_vigente_no_distingue_roles(self) -> None:
        # C-03: el DER no define roles en USER.
        assert describe_policy()["roles"] is False


class TestListado:
    def test_devuelve_los_registros_mas_recientes_primero(
        self, client: APIClient, paciente: Patient
    ) -> None:
        respuesta = client.get(LISTA)
        assert respuesta.status_code == 200
        acciones = [fila["action"] for fila in respuesta.json()["results"]]
        assert acciones[0] == "UPDATE"

    def test_cada_fila_trae_todo_lo_que_exige_la_documentacion(
        self, client: APIClient, paciente: Patient, clinico: User
    ) -> None:
        fila = client.get(LISTA, {"action": "UPDATE"}).json()["results"][0]
        assert fila["username"] == clinico.username  # usuario responsable
        assert fila["entity_type"] == "patient"  # entidad afectada
        assert fila["entity_id"] == paciente.pk  # ID de entidad
        assert fila["action"] == "UPDATE"  # operacion
        assert fila["old_values"]["last_name"] == "Gomez"  # valores anteriores
        assert fila["new_values"]["last_name"] == "Gomez Ruiz"  # valores nuevos
        assert "last_name" in fila["changes"]  # cambios realizados
        assert fila["created_at"]  # fecha/hora

    def test_changes_se_deriva_y_no_es_una_columna(
        self, client: APIClient, paciente: Patient
    ) -> None:
        # D-03: el DER no define una columna `changes`.
        assert not hasattr(AuditLog, "changes")
        fila = client.get(LISTA, {"action": "UPDATE"}).json()["results"][0]
        assert isinstance(fila["changes"], list)

    @pytest.mark.parametrize(
        ("filtro", "esperado"),
        [
            ({"entity_type": "patient"}, True),
            ({"entity_type": "appointment"}, False),
            ({"action": "CREATE"}, True),
            ({"action": "DELETE"}, False),
        ],
    )
    def test_filtros(
        self, client: APIClient, paciente: Patient, filtro: dict, esperado: bool
    ) -> None:
        resultados = client.get(LISTA, filtro).json()["results"]
        assert bool(resultados) is esperado

    def test_filtro_por_entidad_concreta(
        self, client: APIClient, paciente: Patient
    ) -> None:
        resultados = client.get(
            LISTA, {"entity_type": "patient", "entity_id": paciente.pk}
        ).json()["results"]
        assert len(resultados) == 2  # el alta y la modificacion

    def test_el_listado_esta_paginado(
        self, client: APIClient, paciente: Patient
    ) -> None:
        cuerpo = client.get(LISTA).json()
        assert {"count", "next", "previous", "results"} <= set(cuerpo)

    def test_el_listado_no_incurre_en_n_mas_1(
        self, client: APIClient, django_assert_num_queries, clinico: User
    ) -> None:
        with acting_as(clinico):
            for i in range(10):
                Patient.objects.create(first_name=f"P{i}", last_name="Test")

        # Una consulta para el conteo de la paginacion y otra para las filas,
        # con el usuario resuelto por select_related.
        with django_assert_num_queries(2):
            client.get(LISTA)


class TestDetalle:
    def test_devuelve_una_entrada_por_su_id(
        self, client: APIClient, paciente: Patient
    ) -> None:
        registro = AuditLog.objects.filter(entity_type="patient").first()
        respuesta = client.get(f"{LISTA}{registro.audit_id}/")
        assert respuesta.status_code == 200
        assert respuesta.json()["audit_id"] == registro.audit_id

    def test_devuelve_404_si_no_existe(self, client: APIClient) -> None:
        assert client.get(f"{LISTA}999999/").status_code == 404


class TestExportacion:
    def test_exporta_csv(self, client: APIClient, paciente: Patient) -> None:
        respuesta = client.get(EXPORT)
        assert respuesta.status_code == 200
        assert respuesta["Content-Type"] == "text/csv"
        assert "attachment" in respuesta["Content-Disposition"]

        lineas = b"".join(respuesta.streaming_content).decode().strip().splitlines()
        assert lineas[0].startswith("audit_id,created_at,username")
        assert len(lineas) > 1

    def test_el_csv_no_difunde_contenido_clinico(
        self, client: APIClient, paciente: Patient
    ) -> None:
        # Solo nombres de columnas modificadas, nunca sus valores.
        contenido = b"".join(client.get(EXPORT).streaming_content).decode()
        assert "last_name" in contenido
        assert "Gomez Ruiz" not in contenido

    def test_admite_los_mismos_filtros(
        self, client: APIClient, paciente: Patient
    ) -> None:
        contenido = b"".join(
            client.get(EXPORT, {"entity_type": "patient"}).streaming_content
        ).decode()
        assert "patient" in contenido

    def test_rechaza_un_filtro_invalido(self, client: APIClient) -> None:
        assert client.get(EXPORT, {"entity_id": "no-es-un-numero"}).status_code == 400

    def test_un_anonimo_no_puede_exportar(self) -> None:
        assert APIClient().get(EXPORT).status_code == 401
