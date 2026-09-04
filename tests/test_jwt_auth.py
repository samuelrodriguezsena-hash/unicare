"""Tests de autenticacion JWT (FASE 13).

Importante: el resto de la suite usa `force_authenticate`, que **salta la
autenticacion por completo**. Este modulo es el unico que ejercita el camino
real: obtener un token, firmarlo, mandarlo en la cabecera y validarlo.

Es donde se comprueba de verdad la decision C-02: que `core.User`, que hereda
de `AbstractBaseUser` SIN `PermissionsMixin` y cuya PK es `user_id` y no `id`,
funciona con `djangorestframework-simplejwt`.

Requiere PostgreSQL.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.core.models import User
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

OBTENER = "/api/v1/auth/token/"
REFRESCAR = "/api/v1/auth/token/refresh/"
VERIFICAR = "/api/v1/auth/token/verify/"
PACIENTES = "/api/v1/patients/"

PASSWORD = "una-clave-larga-y-valida"


@pytest.fixture
def clinico() -> User:
    return User.objects.create_user(
        username="dra.rojas", email="rojas@example.com", password=PASSWORD
    )


@pytest.fixture
def anonimo() -> APIClient:
    return APIClient()


def autenticar(client: APIClient, token: str) -> APIClient:
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


class TestObtencionDeToken:
    def test_devuelve_access_y_refresh(self, anonimo: APIClient, clinico: User) -> None:
        respuesta = anonimo.post(
            OBTENER, {"username": "dra.rojas", "password": PASSWORD}, format="json"
        )

        assert respuesta.status_code == 200
        cuerpo = respuesta.json()
        assert "access" in cuerpo
        assert "refresh" in cuerpo

    def test_el_endpoint_es_publico(self, anonimo: APIClient) -> None:
        # Sin el, no habria forma de obtener el primer token.
        assert anonimo.post(OBTENER, {}, format="json").status_code == 400

    def test_rechaza_una_contrasena_incorrecta(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        respuesta = anonimo.post(
            OBTENER, {"username": "dra.rojas", "password": "otra"}, format="json"
        )
        assert respuesta.status_code == 401

    def test_rechaza_un_usuario_inexistente(self, anonimo: APIClient) -> None:
        respuesta = anonimo.post(
            OBTENER, {"username": "nadie", "password": PASSWORD}, format="json"
        )
        assert respuesta.status_code == 401

    def test_rechaza_un_usuario_inactivo(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        clinico.is_active = False
        clinico.save(update_fields=["is_active"])

        respuesta = anonimo.post(
            OBTENER, {"username": "dra.rojas", "password": PASSWORD}, format="json"
        )
        assert respuesta.status_code == 401

    def test_el_usuario_tecnico_no_puede_obtener_token(
        self, anonimo: APIClient
    ) -> None:
        """C-04: `system` se crea con contrasena inutilizable."""
        respuesta = anonimo.post(
            OBTENER,
            {"username": settings.SYSTEM_USERNAME, "password": PASSWORD},
            format="json",
        )
        assert respuesta.status_code == 401


class TestCompatibilidadConElDer:
    """C-02: `core.User` sin `PermissionsMixin` y con PK `user_id`."""

    def test_el_token_lleva_la_pk_del_der(self, clinico: User) -> None:
        # simplejwt asume `id` por defecto; el DER define `user_id`.
        token = AccessToken.for_user(clinico)
        assert token["user_id"] == clinico.pk
        assert settings.SIMPLE_JWT["USER_ID_FIELD"] == "user_id"

    def test_el_usuario_no_tiene_permissions_mixin(self, clinico: User) -> None:
        # Si lo tuviera, habria dos tablas M2M fuera del DER.
        assert not hasattr(clinico, "is_superuser")
        assert not hasattr(clinico, "user_permissions")

    def test_aun_asi_la_autenticacion_funciona(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        token = anonimo.post(
            OBTENER, {"username": "dra.rojas", "password": PASSWORD}, format="json"
        ).json()["access"]

        respuesta = autenticar(anonimo, token).get(PACIENTES)
        assert respuesta.status_code == 200

    def test_no_se_crearon_tablas_de_permisos(self) -> None:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                  AND table_name IN ('user_groups', 'user_user_permissions')
                """
            )
            assert cursor.fetchall() == []


class TestUsoDelToken:
    def test_un_token_valido_da_acceso(self, anonimo: APIClient, clinico: User) -> None:
        token = str(AccessToken.for_user(clinico))
        assert autenticar(anonimo, token).get(PACIENTES).status_code == 200

    def test_sin_cabecera_no_hay_acceso(self, anonimo: APIClient) -> None:
        assert anonimo.get(PACIENTES).status_code == 401

    def test_un_token_invalido_no_da_acceso(self, anonimo: APIClient) -> None:
        assert (
            autenticar(anonimo, "esto.no.es-un-token").get(PACIENTES).status_code == 401
        )

    def test_un_token_caducado_no_da_acceso(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        token = AccessToken.for_user(clinico)
        token.set_exp(lifetime=timedelta(seconds=-1))

        assert autenticar(anonimo, str(token)).get(PACIENTES).status_code == 401

    def test_un_token_firmado_con_otra_clave_no_da_acceso(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        import jwt

        falso = jwt.encode(
            {"user_id": clinico.pk, "token_type": "access", "exp": 9999999999},
            "clave-del-atacante",
            algorithm="HS256",
        )
        assert autenticar(anonimo, falso).get(PACIENTES).status_code == 401

    def test_un_refresh_token_no_sirve_como_access(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        refresh = str(RefreshToken.for_user(clinico))
        assert autenticar(anonimo, refresh).get(PACIENTES).status_code == 401

    def test_si_el_usuario_se_desactiva_el_token_deja_de_valer(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        token = str(AccessToken.for_user(clinico))
        clinico.is_active = False
        clinico.save(update_fields=["is_active"])

        assert autenticar(anonimo, token).get(PACIENTES).status_code == 401

    def test_el_token_identifica_al_usuario_en_la_auditoria(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        """Cierra el circuito: JWT -> middleware -> AUDIT_LOG."""
        from apps.core.models import AuditLog

        token = str(AccessToken.for_user(clinico))
        creado = (
            autenticar(anonimo, token)
            .post(
                PACIENTES,
                {
                    "identification_number": "1098765432",
                    "first_name": "Ana",
                    "last_name": "Gomez",
                },
                format="json",
            )
            .json()
        )

        registro = AuditLog.objects.get(
            entity_type="patient", entity_id=creado["patient_id"], action="CREATE"
        )
        assert registro.user_id == clinico.pk


class TestRefresco:
    def test_devuelve_un_access_nuevo(self, anonimo: APIClient, clinico: User) -> None:
        refresh = str(RefreshToken.for_user(clinico))

        respuesta = anonimo.post(REFRESCAR, {"refresh": refresh}, format="json")

        assert respuesta.status_code == 200
        assert "access" in respuesta.json()

    def test_no_rota_el_refresh(self, anonimo: APIClient, clinico: User) -> None:
        """DEC-35: la rotacion exige tablas que el DER no contempla.

        `ROTATE_REFRESH_TOKENS=True` hace que simplejwt llame a
        `refresh.outstand()`, que escribe en `OutstandingToken`, un modelo de
        la app `token_blacklist`. Sin esa app instalada, refrescar responde
        500. Este test fija esa regresion.
        """
        refresh = str(RefreshToken.for_user(clinico))
        cuerpo = anonimo.post(REFRESCAR, {"refresh": refresh}, format="json").json()

        assert "refresh" not in cuerpo
        assert "access" in cuerpo

    def test_el_mismo_refresh_se_puede_reutilizar(
        self, anonimo: APIClient, clinico: User
    ) -> None:
        # Consecuencia directa de no rotar: mitigada por la vida corta.
        refresh = str(RefreshToken.for_user(clinico))
        for _ in range(2):
            respuesta = anonimo.post(REFRESCAR, {"refresh": refresh}, format="json")
            assert respuesta.status_code == 200

    def test_el_access_obtenido_sirve(self, anonimo: APIClient, clinico: User) -> None:
        refresh = str(RefreshToken.for_user(clinico))
        nuevo = anonimo.post(REFRESCAR, {"refresh": refresh}, format="json").json()[
            "access"
        ]

        assert autenticar(anonimo, nuevo).get(PACIENTES).status_code == 200

    def test_rechaza_un_refresh_invalido(self, anonimo: APIClient) -> None:
        respuesta = anonimo.post(REFRESCAR, {"refresh": "invalido"}, format="json")
        assert respuesta.status_code == 401


class TestVerificacion:
    def test_acepta_un_token_valido(self, anonimo: APIClient, clinico: User) -> None:
        token = str(AccessToken.for_user(clinico))
        assert (
            anonimo.post(VERIFICAR, {"token": token}, format="json").status_code == 200
        )

    def test_rechaza_uno_invalido(self, anonimo: APIClient) -> None:
        respuesta = anonimo.post(VERIFICAR, {"token": "invalido"}, format="json")
        assert respuesta.status_code == 401


class TestRevocacion:
    def test_no_hay_rotacion_ni_lista_negra(self) -> None:
        """DEC-35: ambas exigen tablas fuera del DER.

        Consecuencia: un refresh token no se puede revocar antes de que
        caduque. El "logout" es del lado del cliente, y por eso la vida del
        access token es corta.
        """
        assert settings.SIMPLE_JWT["ROTATE_REFRESH_TOKENS"] is False
        assert settings.SIMPLE_JWT["BLACKLIST_AFTER_ROTATION"] is False
        assert "rest_framework_simplejwt.token_blacklist" not in (
            settings.INSTALLED_APPS
        )

    def test_la_vida_del_access_es_corta(self) -> None:
        assert settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"] <= timedelta(minutes=15)


class TestConfiguracion:
    def test_la_clave_de_firma_no_esta_hardcodeada(self) -> None:
        assert settings.SIMPLE_JWT["SIGNING_KEY"] == settings.SECRET_KEY

    def test_jwt_es_la_autenticacion_por_defecto(self) -> None:
        assert settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"] == (
            "rest_framework_simplejwt.authentication.JWTAuthentication",
        )
