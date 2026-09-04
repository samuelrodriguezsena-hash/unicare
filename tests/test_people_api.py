"""Tests de la API de `people` (FASE 6).

Cubren CRUD de pacientes, busqueda, filtros, historial clinico y patologias.
Requieren PostgreSQL: las reglas que se comprueban (UNIQUE compuesta, unica
patologia principal) las impone la base, no el codigo Python.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from rest_framework.test import APIClient

from apps.core.models import AuditLog, User
from apps.people.models import ClinicalHistory, Note, Pathology, Patient
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

PACIENTES = "/api/v1/patients/"
PATOLOGIAS = "/api/v1/pathologies/"


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(username="dra.rojas", password="x" * 14)


@pytest.fixture
def client(clinico: User) -> APIClient:
    api = APIClient()
    api.force_authenticate(user=clinico)
    return api


def nacido_hace(anios: int) -> str:
    """Fecha de nacimiento de alguien que cumplio `anios` ayer.

    Se calcula relativa a hoy para que los tests de edad no caduquen.
    """
    hoy = date.today()
    try:
        nacimiento = hoy.replace(year=hoy.year - anios)
    except ValueError:  # 29 de febrero
        nacimiento = hoy.replace(year=hoy.year - anios, day=28)
    return str(nacimiento - timedelta(days=1))


@pytest.fixture
def datos_paciente() -> dict:
    return {
        "identification_number": "1098765432",
        "first_name": "Ana",
        "last_name": "Gomez",
        "date_of_birth": nacido_hace(46),
        "phone": "3001234567",
        "email": "ana@example.com",
    }


@pytest.fixture
def paciente(client: APIClient, datos_paciente: dict) -> dict:
    return client.post(PACIENTES, datos_paciente, format="json").json()


class TestAltaDePacientes:
    def test_crea_un_paciente(self, client: APIClient, datos_paciente: dict) -> None:
        respuesta = client.post(PACIENTES, datos_paciente, format="json")
        assert respuesta.status_code == 201
        cuerpo = respuesta.json()
        assert cuerpo["identification_number"] == "1098765432"
        assert cuerpo["is_active"] is True

    def test_el_alta_crea_tambien_el_historial_clinico(
        self, client: APIClient, paciente: dict
    ) -> None:
        # El DER modela CLINICAL_HISTORY 1:1 obligatorio con PATIENT.
        assert ClinicalHistory.objects.filter(
            patient_id=paciente["patient_id"]
        ).exists()

    def test_la_identificacion_es_obligatoria_en_la_api(
        self, client: APIClient, datos_paciente: dict
    ) -> None:
        # A-01: en el DER es nullable, pero la documentacion la exige. Se impone
        # en la entrada de la API, no endureciendo el esquema.
        del datos_paciente["identification_number"]
        respuesta = client.post(PACIENTES, datos_paciente, format="json")
        assert respuesta.status_code == 400
        assert "identification_number" in respuesta.json()

    def test_rechaza_una_identificacion_con_formato_invalido(
        self, client: APIClient, datos_paciente: dict
    ) -> None:
        datos_paciente["identification_number"] = "10 98 76"
        assert client.post(PACIENTES, datos_paciente, format="json").status_code == 400

    def test_rechaza_una_identificacion_repetida_con_409(
        self, client: APIClient, paciente: dict, datos_paciente: dict
    ) -> None:
        respuesta = client.post(PACIENTES, datos_paciente, format="json")
        assert respuesta.status_code == 409
        assert respuesta.json()["code"] == "conflict"

    def test_rechaza_una_fecha_de_nacimiento_futura(
        self, client: APIClient, datos_paciente: dict
    ) -> None:
        datos_paciente["date_of_birth"] = str(date.today() + timedelta(days=1))
        assert client.post(PACIENTES, datos_paciente, format="json").status_code == 400

    def test_no_se_puede_crear_un_paciente_ya_inactivo(
        self, client: APIClient, datos_paciente: dict
    ) -> None:
        # `is_active` no es escribible: la baja tiene su propio endpoint.
        datos_paciente["is_active"] = False
        respuesta = client.post(PACIENTES, datos_paciente, format="json")
        assert respuesta.json()["is_active"] is True


class TestConsultaYModificacion:
    def test_detalle(self, client: APIClient, paciente: dict) -> None:
        respuesta = client.get(f"{PACIENTES}{paciente['patient_id']}/")
        assert respuesta.status_code == 200
        assert respuesta.json()["first_name"] == "Ana"

    def test_calcula_la_edad_sin_anadir_columnas(
        self, client: APIClient, paciente: dict
    ) -> None:
        # `age` es derivado: no existe como columna en el DER.
        assert not hasattr(Patient, "age")
        edad = client.get(f"{PACIENTES}{paciente['patient_id']}/").json()["age"]
        assert edad == 46

    def test_la_edad_es_nula_sin_fecha_de_nacimiento(
        self, client: APIClient, datos_paciente: dict
    ) -> None:
        del datos_paciente["date_of_birth"]
        creado = client.post(PACIENTES, datos_paciente, format="json").json()
        assert creado["age"] is None

    def test_actualizacion_parcial(self, client: APIClient, paciente: dict) -> None:
        respuesta = client.patch(
            f"{PACIENTES}{paciente['patient_id']}/",
            {"phone": "3009999999"},
            format="json",
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["phone"] == "3009999999"
        assert respuesta.json()["first_name"] == "Ana"

    def test_no_existe_borrado_de_pacientes(
        self, client: APIClient, paciente: dict
    ) -> None:
        # A-09: el DER define `is_active` para dar de baja.
        respuesta = client.delete(f"{PACIENTES}{paciente['patient_id']}/")
        assert respuesta.status_code == 405

    def test_devuelve_404_si_no_existe(self, client: APIClient) -> None:
        assert client.get(f"{PACIENTES}999999/").status_code == 404


class TestBajaLogica:
    def test_desactiva_sin_borrar(self, client: APIClient, paciente: dict) -> None:
        respuesta = client.post(f"{PACIENTES}{paciente['patient_id']}/deactivate/")
        assert respuesta.status_code == 200
        assert respuesta.json()["is_active"] is False
        assert Patient.objects.filter(pk=paciente["patient_id"]).exists()

    def test_es_idempotente(self, client: APIClient, paciente: dict) -> None:
        url = f"{PACIENTES}{paciente['patient_id']}/deactivate/"
        client.post(url)
        assert client.post(url).status_code == 200


class TestBusquedaYFiltros:
    @pytest.fixture
    def poblacion(self, client: APIClient) -> list[dict]:
        personas = [
            ("1000000001", "Ana", "Gomez", nacido_hace(46)),
            ("1000000002", "Luis", "Perez", nacido_hace(16)),
            ("1000000003", "Marta", "Gomez", nacido_hace(75)),
        ]
        return [
            client.post(
                PACIENTES,
                {
                    "identification_number": ident,
                    "first_name": nombre,
                    "last_name": apellido,
                    "date_of_birth": nacimiento,
                },
                format="json",
            ).json()
            for ident, nombre, apellido, nacimiento in personas
        ]

    def test_busqueda_por_apellido(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(PACIENTES, {"search": "gomez"}).json()["results"]
        assert {p["first_name"] for p in resultados} == {"Ana", "Marta"}

    def test_busqueda_por_nombre(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(PACIENTES, {"search": "Luis"}).json()["results"]
        assert len(resultados) == 1

    def test_busqueda_por_identificacion(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(
            PACIENTES, {"identification_number": "1000000002"}
        ).json()["results"]
        assert resultados[0]["first_name"] == "Luis"

    def test_filtro_por_edad_minima(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(PACIENTES, {"age_min": 60}).json()["results"]
        assert {p["first_name"] for p in resultados} == {"Marta"}

    def test_filtro_por_edad_maxima(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(PACIENTES, {"age_max": 30}).json()["results"]
        assert {p["first_name"] for p in resultados} == {"Luis"}

    def test_filtro_por_rango_de_edad(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        resultados = client.get(PACIENTES, {"age_min": 40, "age_max": 60}).json()[
            "results"
        ]
        assert {p["first_name"] for p in resultados} == {"Ana"}

    def test_filtro_por_estado(self, client: APIClient, poblacion: list[dict]) -> None:
        client.post(f"{PACIENTES}{poblacion[0]['patient_id']}/deactivate/")
        activos = client.get(PACIENTES, {"is_active": "true"}).json()["results"]
        assert len(activos) == 2

    def test_filtro_por_patologia_principal(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        otra = Pathology.objects.create(name="Melanoma")
        client.post(
            f"{PACIENTES}{poblacion[0]['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk, "is_primary": True},
            format="json",
        )
        # Asociada pero NO principal: no debe aparecer en el filtro.
        client.post(
            f"{PACIENTES}{poblacion[1]['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk, "is_primary": False},
            format="json",
        )
        client.post(
            f"{PACIENTES}{poblacion[2]['patient_id']}/pathologies/",
            {"pathology_id": otra.pk, "is_primary": True},
            format="json",
        )

        resultados = client.get(PACIENTES, {"primary_pathology": patologia.pk}).json()[
            "results"
        ]
        assert {p["first_name"] for p in resultados} == {"Ana"}

    def test_el_listado_esta_paginado_y_ordenado(
        self, client: APIClient, poblacion: list[dict]
    ) -> None:
        cuerpo = client.get(PACIENTES).json()
        assert {"count", "next", "previous", "results"} <= set(cuerpo)
        apellidos = [p["last_name"] for p in cuerpo["results"]]
        assert apellidos == sorted(apellidos)


class TestRendimiento:
    def test_el_listado_no_incurre_en_n_mas_1(
        self, client: APIClient, django_assert_max_num_queries
    ) -> None:
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        for i in range(10):
            creado = client.post(
                PACIENTES,
                {
                    "identification_number": f"200000000{i}",
                    "first_name": f"P{i}",
                    "last_name": "Test",
                },
                format="json",
            ).json()
            client.post(
                f"{PACIENTES}{creado['patient_id']}/pathologies/",
                {"pathology_id": patologia.pk, "is_primary": True},
                format="json",
            )

        # Conteo de paginacion + pacientes + prefetch de patologias principales.
        # Sin el Prefetch serian 10 consultas extra, una por paciente.
        with django_assert_max_num_queries(4):
            client.get(PACIENTES)


class TestPatologiasDelPaciente:
    @pytest.fixture
    def patologia(self) -> Pathology:
        return Pathology.objects.create(name="Carcinoma ductal")

    def test_asocia_una_patologia(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        respuesta = client.post(
            f"{PACIENTES}{paciente['patient_id']}/pathologies/",
            {
                "pathology_id": patologia.pk,
                "is_primary": True,
                "diagnosis_date": "2026-01-15",
            },
            format="json",
        )
        assert respuesta.status_code == 201
        assert respuesta.json()["pathology"]["name"] == "Carcinoma ductal"

    def test_no_admite_la_misma_patologia_dos_veces(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        url = f"{PACIENTES}{paciente['patient_id']}/pathologies/"
        client.post(url, {"pathology_id": patologia.pk}, format="json")
        respuesta = client.post(url, {"pathology_id": patologia.pk}, format="json")
        assert respuesta.status_code == 409
        assert "ya tiene asociada" in respuesta.json()["detail"]

    def test_solo_admite_una_patologia_principal(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        otra = Pathology.objects.create(name="Melanoma")
        url = f"{PACIENTES}{paciente['patient_id']}/pathologies/"
        client.post(
            url, {"pathology_id": patologia.pk, "is_primary": True}, format="json"
        )

        respuesta = client.post(
            url, {"pathology_id": otra.pk, "is_primary": True}, format="json"
        )
        assert respuesta.status_code == 409
        assert "principal" in respuesta.json()["detail"]

    def test_la_patologia_principal_aparece_en_el_paciente(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        client.post(
            f"{PACIENTES}{paciente['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk, "is_primary": True},
            format="json",
        )
        detalle = client.get(f"{PACIENTES}{paciente['patient_id']}/").json()
        assert detalle["primary_pathology"]["pathology"]["name"] == "Carcinoma ductal"

    def test_desasocia_una_patologia(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        creada = client.post(
            f"{PACIENTES}{paciente['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk},
            format="json",
        ).json()
        url = f"/api/v1/patient-pathologies/{creada['patient_pathology_id']}/"
        assert client.delete(url).status_code == 204
        assert client.delete(url).status_code == 404

    def test_modifica_una_asociacion(
        self, client: APIClient, paciente: dict, patologia: Pathology
    ) -> None:
        creada = client.post(
            f"{PACIENTES}{paciente['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk},
            format="json",
        ).json()
        respuesta = client.patch(
            f"/api/v1/patient-pathologies/{creada['patient_pathology_id']}/",
            {"notes": "Estadio II"},
            format="json",
        )
        assert respuesta.status_code == 200
        assert respuesta.json()["notes"] == "Estadio II"


class TestHistorialClinico:
    def test_devuelve_el_historial_del_paciente(
        self, client: APIClient, paciente: dict
    ) -> None:
        respuesta = client.get(f"{PACIENTES}{paciente['patient_id']}/clinical-history/")
        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["patient"] == paciente["patient_id"]
        assert cuerpo["entries"] == []
        assert cuerpo["notes"] == []

    def test_registra_entradas_del_historial(
        self, client: APIClient, paciente: dict
    ) -> None:
        historial = client.get(
            f"{PACIENTES}{paciente['patient_id']}/clinical-history/"
        ).json()
        url = f"/api/v1/clinical-histories/{historial['clinical_history_id']}/entries/"

        respuesta = client.post(
            url,
            {
                "entry_type": "DIAGNOSIS",
                "entry_date": "2026-02-01",
                "description": "Diagnostico inicial",
            },
            format="json",
        )
        assert respuesta.status_code == 201
        assert client.get(url).json()["results"][0]["description"] == (
            "Diagnostico inicial"
        )

    def test_rechaza_un_tipo_de_entrada_fuera_del_enum(
        self, client: APIClient, paciente: dict
    ) -> None:
        historial = client.get(
            f"{PACIENTES}{paciente['patient_id']}/clinical-history/"
        ).json()
        respuesta = client.post(
            f"/api/v1/clinical-histories/{historial['clinical_history_id']}/entries/",
            {
                "entry_type": "INVENTADO",
                "entry_date": "2026-02-01",
                "description": "x",
            },
            format="json",
        )
        assert respuesta.status_code == 400

    def test_registra_notas(self, client: APIClient, paciente: dict) -> None:
        historial = client.get(
            f"{PACIENTES}{paciente['patient_id']}/clinical-history/"
        ).json()
        url = f"/api/v1/clinical-histories/{historial['clinical_history_id']}/notes/"

        assert (
            client.post(url, {"text": "Tolera bien"}, format="json").status_code == 201
        )
        assert Note.objects.count() == 1

    def test_no_se_crea_una_estructura_paralela_de_historial(
        self, client: APIClient, paciente: dict
    ) -> None:
        # Las entradas van a CLINICAL_HISTORY_ENTRY, no a una tabla nueva.
        historial = client.get(
            f"{PACIENTES}{paciente['patient_id']}/clinical-history/"
        ).json()
        assert set(historial) == {
            "clinical_history_id",
            "patient",
            "pathologies",
            "entries",
            "notes",
            "last_ai_summary",
            "last_ai_summary_at",
            "created_at",
            "updated_at",
        }


class TestPatologias:
    def test_crea_y_lista(self, client: APIClient) -> None:
        assert (
            client.post(
                PATOLOGIAS, {"name": "Carcinoma ductal"}, format="json"
            ).status_code
            == 201
        )
        assert client.get(PATOLOGIAS).json()["count"] == 1

    def test_el_nombre_es_unico(self, client: APIClient) -> None:
        client.post(PATOLOGIAS, {"name": "Melanoma"}, format="json")
        assert (
            client.post(PATOLOGIAS, {"name": "Melanoma"}, format="json").status_code
            == 400
        )

    def test_no_expone_borrado(self, client: APIClient) -> None:
        creada = client.post(PATOLOGIAS, {"name": "Melanoma"}, format="json").json()
        respuesta = client.delete(f"{PATOLOGIAS}{creada['pathology_id']}/")
        assert respuesta.status_code == 405


class TestSeguridad:
    @pytest.mark.parametrize(
        ("metodo", "url"),
        [
            ("get", PACIENTES),
            ("post", PACIENTES),
            ("get", PATOLOGIAS),
            ("post", PATOLOGIAS),
        ],
    )
    def test_un_anonimo_no_puede_operar(self, metodo: str, url: str) -> None:
        respuesta = getattr(APIClient(), metodo)(url)
        assert respuesta.status_code == 401

    def test_un_usuario_inactivo_tampoco(self) -> None:
        inactivo = User.objects.create_user(username="baja", password="z" * 14)
        inactivo.is_active = False
        api = APIClient()
        api.force_authenticate(user=inactivo)
        assert api.get(PACIENTES).status_code == 403


class TestAuditoriaDeExtremoAExtremo:
    """Cierra el circuito: peticion HTTP real -> middleware -> AUDIT_LOG."""

    def test_el_alta_queda_auditada_con_el_usuario_de_la_peticion(
        self, client: APIClient, clinico: User, datos_paciente: dict
    ) -> None:
        creado = client.post(PACIENTES, datos_paciente, format="json").json()

        registro = AuditLog.objects.get(
            entity_type="patient", entity_id=creado["patient_id"], action="CREATE"
        )
        assert registro.user_id == clinico.pk

    def test_la_baja_logica_queda_auditada_como_modificacion(
        self, client: APIClient, paciente: dict
    ) -> None:
        client.post(f"{PACIENTES}{paciente['patient_id']}/deactivate/")

        registro = AuditLog.objects.filter(
            entity_type="patient",
            entity_id=paciente["patient_id"],
            action="UPDATE",
        ).latest("audit_id")
        assert registro.old_values["is_active"] is True
        assert registro.new_values["is_active"] is False

    def test_created_by_se_rellena_desde_la_peticion(
        self, client: APIClient, clinico: User, paciente: dict
    ) -> None:
        assert (
            Patient.objects.get(pk=paciente["patient_id"]).created_by_id == clinico.pk
        )


class TestConflictosAlModificar:
    def test_no_se_puede_reusar_la_identificacion_de_otro_paciente(
        self, client: APIClient, paciente: dict, datos_paciente: dict
    ) -> None:
        otro = client.post(
            PACIENTES,
            {**datos_paciente, "identification_number": "1111111111"},
            format="json",
        ).json()

        respuesta = client.patch(
            f"{PACIENTES}{otro['patient_id']}/",
            {"identification_number": paciente["identification_number"]},
            format="json",
        )
        assert respuesta.status_code == 409

    def test_no_se_puede_promover_una_segunda_patologia_a_principal(
        self, client: APIClient, paciente: dict
    ) -> None:
        principal = Pathology.objects.create(name="Carcinoma ductal")
        secundaria = Pathology.objects.create(name="Melanoma")
        url = f"{PACIENTES}{paciente['patient_id']}/pathologies/"
        client.post(
            url, {"pathology_id": principal.pk, "is_primary": True}, format="json"
        )
        otra = client.post(url, {"pathology_id": secundaria.pk}, format="json").json()

        respuesta = client.patch(
            f"/api/v1/patient-pathologies/{otra['patient_pathology_id']}/",
            {"is_primary": True},
            format="json",
        )
        assert respuesta.status_code == 409
        assert "principal" in respuesta.json()["detail"]


class TestHistorialAusente:
    def test_se_crea_al_vuelo_si_el_paciente_no_lo_tenia(
        self, client: APIClient, paciente: dict
    ) -> None:
        """Los pacientes creados por carga masiva podrian no tener historial."""
        ClinicalHistory.objects.filter(patient_id=paciente["patient_id"]).delete()

        respuesta = client.get(f"{PACIENTES}{paciente['patient_id']}/clinical-history/")
        assert respuesta.status_code == 200
        assert ClinicalHistory.objects.filter(
            patient_id=paciente["patient_id"]
        ).exists()


class TestBusquedaVacia:
    def test_un_termino_en_blanco_no_filtra_nada(
        self, client: APIClient, paciente: dict
    ) -> None:
        assert client.get(PACIENTES, {"search": "   "}).json()["count"] == 1


class TestListadosDeLectura:
    """Los `GET` de las colecciones anidadas, que no cubrian otros tests."""

    def test_lista_las_patologias_del_paciente(
        self, client: APIClient, paciente: dict
    ) -> None:
        principal = Pathology.objects.create(name="Carcinoma ductal")
        secundaria = Pathology.objects.create(name="Melanoma")
        url = f"{PACIENTES}{paciente['patient_id']}/pathologies/"
        client.post(url, {"pathology_id": secundaria.pk}, format="json")
        client.post(
            url, {"pathology_id": principal.pk, "is_primary": True}, format="json"
        )

        respuesta = client.get(url)

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert len(cuerpo) == 2
        # La principal va primero.
        assert cuerpo[0]["pathology"]["name"] == "Carcinoma ductal"

    def test_solo_devuelve_las_del_paciente_pedido(
        self, client: APIClient, paciente: dict, datos_paciente: dict
    ) -> None:
        otro = client.post(
            PACIENTES,
            {**datos_paciente, "identification_number": "2222222222"},
            format="json",
        ).json()
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        client.post(
            f"{PACIENTES}{paciente['patient_id']}/pathologies/",
            {"pathology_id": patologia.pk},
            format="json",
        )

        assert client.get(f"{PACIENTES}{otro['patient_id']}/pathologies/").json() == []

    def test_lista_las_notas_del_historial(
        self, client: APIClient, paciente: dict
    ) -> None:
        historial = client.get(
            f"{PACIENTES}{paciente['patient_id']}/clinical-history/"
        ).json()
        url = f"/api/v1/clinical-histories/{historial['clinical_history_id']}/notes/"
        client.post(url, {"text": "Primera nota"}, format="json")
        client.post(url, {"text": "Segunda nota"}, format="json")

        respuesta = client.get(url)

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert cuerpo["count"] == 2
        # Mas recientes primero.
        assert cuerpo["results"][0]["text"] == "Segunda nota"


class TestConflictoInesperado:
    def test_un_integrityerror_desconocido_se_traduce_a_409(
        self, client: APIClient, paciente: dict
    ) -> None:
        """Fallback: nunca debe escapar como un 500 con traza."""
        from django.db import IntegrityError

        from apps.core.exceptions import ConflictError
        from apps.people.services.pathologies import PathologyService

        traducido = PathologyService._traducir(
            IntegrityError("violacion de una restriccion no contemplada")
        )
        assert isinstance(traducido, ConflictError)
        assert traducido.status_code == 409
