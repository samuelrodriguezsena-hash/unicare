"""Tests de la integracion con la API externa de farmacos.

NINGUN test sale a Internet: `respx` intercepta el transporte de httpx. Si
alguna ruta quedara sin mockear, `respx` levanta `AllMockedAssertionError` en
lugar de hacer la peticion real.

No se necesita PostgreSQL: el endpoint no toca la base, y la autenticacion se
resuelve con `force_authenticate` sobre un usuario no persistido.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
import respx
from django.test import override_settings
from rest_framework.test import APIClient

from apps.core.models import User
from apps.medications.services import farmacos_api

URL = "/api/v1/farmacos/"
EXTERNAL_URL = "https://farmacos.invalid/v1/farmacos"

FARMACO = {
    "Nombre_Medicamento": "Atorvastatina",
    "Dosis_Comun": "20 mg",
    "Compuesto_Principal": "Atorvastatina",
    "Patologia_Comun": "Colesterol Alto",
    "Familia_Farmaco": "Estatinas",
}
SERTRALINA = {
    "Nombre_Medicamento": "Sertralina",
    "Dosis_Comun": "50 mg",
    "Compuesto_Principal": "Sertralina",
    "Patologia_Comun": "Depresion",
    "Familia_Farmaco": "ISRS",
}


@pytest.fixture(autouse=True)
def _reset_http_client() -> Any:
    """Evita que el cliente httpx compartido se filtre entre tests."""
    farmacos_api.reset_client()
    yield
    farmacos_api.reset_client()


@pytest.fixture
def client() -> APIClient:
    """Cliente autenticado.

    El usuario NO se guarda en base: `IsAuthenticated` solo consulta
    `user.is_authenticated`, que es True en cualquier instancia de
    `AbstractBaseUser`.
    """
    api_client = APIClient()
    api_client.force_authenticate(user=User(user_id=1, username="clinico"))
    return api_client


class TestAutenticacion:
    def test_un_anonimo_no_puede_consultar_farmacos(self) -> None:
        # Se respeta la politica JWT global del proyecto; no se relaja.
        response = APIClient().get(URL)
        assert response.status_code == 401

    @respx.mock
    def test_el_jwt_del_usuario_no_se_reenvia_a_la_api_externa(
        self, client: APIClient
    ) -> None:
        route = respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[FARMACO])
        )
        client.credentials(HTTP_AUTHORIZATION="Bearer token-del-usuario")
        client.get(URL)

        enviadas = route.calls.last.request.headers
        assert enviadas.get("authorization") is None


class TestConsultas:
    @respx.mock
    def test_caso_1_obtener_todos_los_farmacos(self, client: APIClient) -> None:
        route = respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[FARMACO, SERTRALINA])
        )
        response = client.get(URL)

        assert response.status_code == 200
        assert response.json() == [FARMACO, SERTRALINA]
        # Sin filtros no se envia ningun query param.
        assert route.calls.last.request.url.params == httpx.QueryParams()

    @respx.mock
    def test_caso_2_filtrar_por_nombre(self, client: APIClient) -> None:
        route = respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[SERTRALINA])
        )
        response = client.get(URL, {"Nombre_Medicamento": "Sertralina"})

        assert response.status_code == 200
        assert response.json() == [SERTRALINA]
        params = route.calls.last.request.url.params
        assert params["Nombre_Medicamento"] == "Sertralina"
        assert len(params) == 1

    @respx.mock
    def test_caso_3_filtrar_por_familia(self, client: APIClient) -> None:
        route = respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[FARMACO])
        )
        response = client.get(URL, {"Familia_Farmaco": "Estatinas"})

        assert response.status_code == 200
        assert route.calls.last.request.url.params["Familia_Farmaco"] == "Estatinas"

    @respx.mock
    def test_caso_4_multiples_filtros_con_espacios(self, client: APIClient) -> None:
        route = respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        response = client.get(
            URL, {"Patologia_Comun": "Diabetes Tipo 2", "Dosis_Comun": "850 mg"}
        )

        assert response.status_code == 200
        params = route.calls.last.request.url.params
        # httpx hace el encoding; los valores llegan intactos al otro lado.
        assert params["Patologia_Comun"] == "Diabetes Tipo 2"
        assert params["Dosis_Comun"] == "850 mg"
        assert len(params) == 2

    @respx.mock
    def test_caso_5_cero_resultados_es_200_y_lista_vacia(
        self, client: APIClient
    ) -> None:
        # `200 + []` NO es un error: es "sin resultados".
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        response = client.get(URL, {"Nombre_Medicamento": "Inexistente"})

        assert response.status_code == 200
        assert response.json() == []

    @respx.mock
    def test_solo_se_devuelven_los_cinco_campos_del_contrato(
        self, client: APIClient
    ) -> None:
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(
                200, json=[{**FARMACO, "campo_interno_del_proveedor": "x"}]
            )
        )
        response = client.get(URL)

        assert response.status_code == 200
        assert response.json() == [FARMACO]


class TestValidacionDeFiltros:
    @respx.mock
    def test_caso_6_parametro_desconocido_devuelve_400(self, client: APIClient) -> None:
        route = respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        response = client.get(URL, {"parametro_inventado": "test"})

        assert response.status_code == 400
        assert "parametro_inventado" in response.json()
        # No se llega a molestar al servicio externo.
        assert not route.called

    @respx.mock
    def test_un_filtro_valido_junto_a_uno_invalido_tambien_falla(
        self, client: APIClient
    ) -> None:
        route = respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        response = client.get(URL, {"Familia_Farmaco": "Estatinas", "orden": "asc"})

        assert response.status_code == 400
        assert not route.called

    @respx.mock
    def test_un_filtro_vacio_se_ignora_y_no_se_reenvia(self, client: APIClient) -> None:
        """`?Nombre_Medicamento=` equivale a no enviar el filtro.

        Es el comportamiento estandar de DRF con query strings, y ademas el
        seguro: reenviar `Nombre_Medicamento=` a la API externa seria pedirle
        una coincidencia exacta con la cadena vacia.
        """
        route = respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[FARMACO])
        )
        response = client.get(f"{URL}?Nombre_Medicamento=")

        assert response.status_code == 200
        assert route.calls.last.request.url.params == httpx.QueryParams()


class TestErroresDeLaApiExterna:
    @respx.mock
    def test_caso_7_la_api_externa_devuelve_400(self, client: APIClient) -> None:
        # Los filtros los aporta el cliente: el problema le es atribuible.
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(400, json={"error": "bad filter"})
        )
        response = client.get(URL, {"Dosis_Comun": "??"})

        assert response.status_code == 400
        assert response.json()["code"] == "farmacos_api_bad_request"

    @respx.mock
    def test_la_api_externa_devuelve_404(self, client: APIClient) -> None:
        # 404 NO significa "sin resultados": el endpoint no existe.
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(404))
        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["code"] == "farmacos_api_error"

    @respx.mock
    def test_caso_8_la_api_externa_devuelve_500(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(500))
        response = client.get(URL)

        assert response.status_code == 502

    @respx.mock
    def test_caso_9_timeout(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(side_effect=httpx.TimeoutException("timeout"))
        response = client.get(URL)

        assert response.status_code == 504
        assert response.json()["code"] == "farmacos_api_timeout"

    @respx.mock
    def test_caso_10_error_de_conexion(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(side_effect=httpx.ConnectError("sin ruta"))
        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["code"] == "farmacos_api_connection_error"

    @respx.mock
    def test_otros_fallos_de_transporte_son_502(self, client: APIClient) -> None:
        # Cualquier httpx.HTTPError no contemplado arriba sigue siendo un fallo
        # de integracion, nunca un 500 nuestro.
        respx.get(EXTERNAL_URL).mock(side_effect=httpx.ReadError("socket roto"))
        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["code"] == "farmacos_api_error"

    @respx.mock
    def test_caso_11_json_invalido(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(
                200,
                content=b"esto no es json",
                headers={"Content-Type": "application/json"},
            )
        )
        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["code"] == "farmacos_api_response_error"

    @respx.mock
    def test_caso_12_la_respuesta_no_es_una_lista(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json={"error": "unexpected"})
        )
        response = client.get(URL)

        assert response.status_code == 502
        assert response.json()["code"] == "farmacos_api_response_error"

    @respx.mock
    def test_los_elementos_deben_ser_objetos(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=["Atorvastatina"])
        )
        response = client.get(URL)

        assert response.status_code == 502

    @respx.mock
    def test_un_campo_obligatorio_ausente_es_error_de_integracion(
        self, client: APIClient
    ) -> None:
        incompleto = {k: v for k, v in FARMACO.items() if k != "Familia_Farmaco"}
        respx.get(EXTERNAL_URL).mock(
            return_value=httpx.Response(200, json=[incompleto])
        )
        response = client.get(URL)

        assert response.status_code == 502

    @respx.mock
    def test_los_errores_no_exponen_detalles_internos(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(500))
        response = client.get(URL)

        cuerpo = str(response.json())
        assert "farmacos.invalid" not in cuerpo
        assert "Traceback" not in cuerpo
        assert "httpx" not in cuerpo


class TestClienteHttp:
    @respx.mock
    def test_el_timeout_se_toma_de_la_configuracion(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        with override_settings(FARMACOS_API_TIMEOUT=3.5):
            farmacos_api.reset_client()
            client.get(URL)
            assert farmacos_api.get_client().timeout.read == 3.5

    def test_nunca_se_usa_timeout_none(self) -> None:
        assert farmacos_api.get_client().timeout.connect is not None

    @respx.mock
    def test_la_api_key_se_envia_solo_si_esta_configurada(
        self, client: APIClient
    ) -> None:
        route = respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        with override_settings(FARMACOS_API_KEY="clave-externa"):
            farmacos_api.reset_client()
            client.get(URL)

        assert route.calls.last.request.headers["authorization"] == (
            "Bearer clave-externa"
        )

    @respx.mock
    def test_el_cliente_se_reutiliza_entre_peticiones(self, client: APIClient) -> None:
        respx.get(EXTERNAL_URL).mock(return_value=httpx.Response(200, json=[]))
        client.get(URL)
        primero = farmacos_api.get_client()
        client.get(URL)
        assert farmacos_api.get_client() is primero

    def test_la_url_externa_no_esta_hardcodeada_en_el_codigo(self) -> None:
        from pathlib import Path

        fuente = Path(farmacos_api.__file__).read_text(encoding="utf-8")
        assert "https://" not in fuente
        assert farmacos_api.FARMACOS_ENDPOINT_PATH == "/v1/farmacos"
