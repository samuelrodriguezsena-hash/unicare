"""Tests de la integracion con Sentry (FASE 14).

No se inicializa Sentry ni se envia nada: se prueba la logica de saneado, que
es exactamente lo que hay que verificar en un sistema con informacion clinica.

No requieren PostgreSQL.
"""

from __future__ import annotations

import pytest

from apps.core.observability import (
    CLAVES_CLINICAS,
    CLAVES_SENSIBLES,
    REDACTADO,
    before_send,
    init_sentry,
    scrub,
    sentry_options,
)

DSN = "https://clave@o0.ingest.sentry.io/0"


class TestSaneado:
    @pytest.mark.parametrize("clave", CLAVES_SENSIBLES)
    def test_redacta_las_claves_sensibles(self, clave: str) -> None:
        assert scrub({clave: "valor"})[clave] == REDACTADO

    @pytest.mark.parametrize("clave", CLAVES_CLINICAS)
    def test_redacta_las_claves_clinicas(self, clave: str) -> None:
        assert scrub({clave: "valor"})[clave] == REDACTADO

    def test_la_coincidencia_es_parcial(self) -> None:
        # Cubre `gemini_api_key`, `HTTP_AUTHORIZATION`, `patient_email`...
        saneado = scrub(
            {
                "GEMINI_API_KEY": "secreta",
                "HTTP_AUTHORIZATION": "Bearer x",
                "patient_email": "ana@example.com",
            }
        )
        assert set(saneado.values()) == {REDACTADO}

    def test_conserva_lo_que_no_es_sensible(self) -> None:
        saneado = scrub({"endpoint": "/api/v1/patients/", "status_code": 500})
        assert saneado == {"endpoint": "/api/v1/patients/", "status_code": 500}

    def test_recorre_estructuras_anidadas(self) -> None:
        saneado = scrub({"nivel1": {"nivel2": [{"password": "x", "ok": 1}]}})
        assert saneado["nivel1"]["nivel2"][0]["password"] == REDACTADO
        assert saneado["nivel1"]["nivel2"][0]["ok"] == 1

    def test_recorre_tuplas(self) -> None:
        assert scrub(({"token": "x"},))[0]["token"] == REDACTADO


class TestBeforeSend:
    def test_elimina_el_cuerpo_de_la_peticion(self) -> None:
        """El cuerpo puede contener un historial clinico entero."""
        evento = {
            "request": {
                "url": "/api/v1/patients/",
                "data": {"first_name": "Ana", "description": "Carcinoma ductal"},
            }
        }
        resultado = before_send(evento, {})

        assert "data" not in resultado["request"]
        assert resultado["request"]["url"] == "/api/v1/patients/"

    def test_elimina_cabeceras_y_cookies(self) -> None:
        evento = {
            "request": {
                "headers": {"Authorization": "Bearer x"},
                "cookies": {"sessionid": "y"},
            }
        }
        resultado = before_send(evento, {})

        assert "headers" not in resultado["request"]
        assert "cookies" not in resultado["request"]

    def test_vacia_la_query_string(self) -> None:
        # Un filtro puede llevar el nombre o la identificacion de un paciente.
        evento = {"request": {"query_string": "search=Gomez&identification=109"}}
        assert before_send(evento, {})["request"]["query_string"] == ""

    def test_del_usuario_solo_sale_el_id(self) -> None:
        evento = {
            "user": {
                "id": 7,
                "email": "rojas@example.com",
                "username": "dra.rojas",
                "ip_address": "10.0.0.1",
            }
        }
        assert set(before_send(evento, {})["user"]) == {"id"}

    def test_sanea_extra_contexts_y_tags(self) -> None:
        evento = {
            "extra": {"password": "x"},
            "contexts": {"datos": {"notes": "biopsia"}},
            "tags": {"api_key": "x"},
        }
        resultado = before_send(evento, {})

        assert resultado["extra"]["password"] == REDACTADO
        assert resultado["contexts"]["datos"]["notes"] == REDACTADO
        assert resultado["tags"]["api_key"] == REDACTADO

    def test_tolera_un_evento_minimo(self) -> None:
        assert before_send({}, {}) == {"user": {"id": None}}

    def test_conserva_lo_necesario_para_diagnosticar(self) -> None:
        evento = {
            "exception": {"values": [{"type": "ValueError"}]},
            "request": {"url": "/api/v1/patients/", "method": "POST"},
        }
        resultado = before_send(evento, {})

        assert resultado["exception"]["values"][0]["type"] == "ValueError"
        assert resultado["request"]["method"] == "POST"


class TestUsuarioResponsable:
    def test_adjunta_el_id_del_usuario_de_la_operacion(self) -> None:
        from apps.core.context import acting_as
        from apps.core.models import User

        with acting_as(User(user_id=7, username="dra.rojas")):
            assert before_send({}, {})["user"] == {"id": "7"}

    def test_sin_usuario_queda_nulo(self) -> None:
        assert before_send({}, {})["user"] == {"id": None}


class TestOpciones:
    def test_nunca_se_envia_el_cuerpo_de_la_peticion(self) -> None:
        # El valor por defecto de sentry-sdk es "medium", que SI lo envia.
        assert sentry_options(DSN)["max_request_body_size"] == "never"

    def test_no_se_envia_pii_por_defecto(self) -> None:
        assert sentry_options(DSN)["send_default_pii"] is False

    def test_el_saneador_esta_enganchado(self) -> None:
        assert sentry_options(DSN)["before_send"] is before_send

    def test_registra_errores_de_django_celery_y_logging(self) -> None:
        nombres = {type(i).__name__ for i in sentry_options(DSN)["integrations"]}
        assert nombres == {
            "DjangoIntegration",
            "CeleryIntegration",
            "LoggingIntegration",
        }

    def test_el_dsn_viene_de_fuera(self) -> None:
        assert sentry_options(DSN)["dsn"] == DSN

    def test_la_traza_de_rendimiento_es_configurable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENTRY_TRACES_SAMPLE_RATE", "0.5")
        assert sentry_options(DSN)["traces_sample_rate"] == 0.5

    def test_el_entorno_es_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SENTRY_ENVIRONMENT", "staging")
        assert sentry_options(DSN)["environment"] == "staging"


class TestInicializacion:
    def test_sin_dsn_queda_desactivado(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SENTRY_DSN", raising=False)
        assert init_sentry() is False

    def test_un_dsn_en_blanco_tampoco_activa(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SENTRY_DSN", "   ")
        assert init_sentry() is False

    def test_con_dsn_se_activa(self, monkeypatch: pytest.MonkeyPatch) -> None:
        llamadas: list[dict] = []
        monkeypatch.setenv("SENTRY_DSN", DSN)
        monkeypatch.setattr("sentry_sdk.init", lambda **kwargs: llamadas.append(kwargs))

        assert init_sentry() is True
        assert llamadas[0]["dsn"] == DSN


class TestSinSecretosEnElRepositorio:
    def test_el_dsn_no_esta_hardcodeado(self) -> None:
        from pathlib import Path

        for fichero in list(Path("apps").rglob("*.py")) + list(
            Path("config").rglob("*.py")
        ):
            texto = fichero.read_text(encoding="utf-8")
            assert "ingest.sentry.io" not in texto


class TestMigasDePan:
    def test_sanea_los_datos_de_las_migas(self) -> None:
        """Las migas de pan tambien viajan a Sentry."""
        evento = {
            "breadcrumbs": {
                "values": [
                    {"message": "guardando", "data": {"notes": "biopsia positiva"}},
                    {"message": "sin data"},
                ]
            }
        }
        resultado = before_send(evento, {})

        assert resultado["breadcrumbs"]["values"][0]["data"]["notes"] == REDACTADO
        assert resultado["breadcrumbs"]["values"][1] == {"message": "sin data"}
