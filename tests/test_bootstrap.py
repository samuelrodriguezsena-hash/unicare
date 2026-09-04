"""Smoke tests de las FASES 1 y 2.

Verifican que el bootstrap del proyecto y la configuracion por entorno son
coherentes. Ninguno de estos tests toca PostgreSQL: el objetivo es que el
arranque quede cubierto aunque la base todavia no exista.

La suite completa (modelos, API, integraciones) llega en la FASE 15.
"""

from __future__ import annotations

import importlib

import pytest
from django.conf import settings
from rest_framework.test import APIClient

from config.settings.base import ImproperlyConfigured, env, env_bool, env_int, env_list


class TestEnvHelpers:
    def test_env_devuelve_el_valor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNICARE_TEST_VAR", "valor")
        assert env("UNICARE_TEST_VAR") == "valor"

    def test_env_usa_el_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("UNICARE_TEST_VAR", raising=False)
        assert env("UNICARE_TEST_VAR", "default") == "default"

    def test_env_falla_si_es_obligatoria_y_falta(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("UNICARE_TEST_VAR", raising=False)
        with pytest.raises(ImproperlyConfigured):
            env("UNICARE_TEST_VAR")

    @pytest.mark.parametrize(
        ("raw", "esperado"),
        [("1", True), ("true", True), ("YES", True), ("on", True), ("0", False)],
    )
    def test_env_bool(
        self, monkeypatch: pytest.MonkeyPatch, raw: str, esperado: bool
    ) -> None:
        monkeypatch.setenv("UNICARE_TEST_BOOL", raw)
        assert env_bool("UNICARE_TEST_BOOL") is esperado

    def test_env_int(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNICARE_TEST_INT", "42")
        assert env_int("UNICARE_TEST_INT", 7) == 42
        monkeypatch.setenv("UNICARE_TEST_INT", "")
        assert env_int("UNICARE_TEST_INT", 7) == 7

    def test_env_list_ignora_vacios(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("UNICARE_TEST_LIST", "a, b ,,c")
        assert env_list("UNICARE_TEST_LIST") == ["a", "b", "c"]


class TestConfiguracion:
    def test_las_cinco_apps_del_proyecto_estan_instaladas(self) -> None:
        for app in (
            "apps.core",
            "apps.people",
            "apps.medications",
            "apps.appointments",
            "apps.massive_load",
        ):
            assert app in settings.INSTALLED_APPS

    def test_el_admin_no_esta_instalado(self) -> None:
        # C-02 opcion 3: sin PermissionsMixin el admin no es utilizable.
        assert "django.contrib.admin" not in settings.INSTALLED_APPS

    def test_auth_user_model_apunta_al_der(self) -> None:
        assert settings.AUTH_USER_MODEL == "core.User"

    def test_la_base_de_datos_es_postgresql(self) -> None:
        # El proyecto nunca asume SQLite.
        assert "postgresql" in settings.DATABASES["default"]["ENGINE"]

    def test_use_tz_activo(self) -> None:
        # DEC-12: timestamptz. Los recordatorios dependen de ello.
        assert settings.USE_TZ is True

    def test_los_endpoints_exigen_autenticacion_por_defecto(self) -> None:
        assert settings.REST_FRAMEWORK["DEFAULT_PERMISSION_CLASSES"] == (
            "rest_framework.permissions.IsAuthenticated",
        )

    def test_offsets_de_recordatorios(self) -> None:
        assert settings.REMINDER_OFFSETS_HOURS == [48, 24]

    def test_no_hay_secretos_con_valor_por_defecto(self) -> None:
        # GEMINI_API_KEY y SENTRY_DSN deben venir del entorno, vacios en tests.
        assert settings.GEMINI_API_KEY == ""

    def test_la_advertencia_de_ia_esta_configurada(self) -> None:
        # Regla clinica: toda salida de IA se identifica y se acompana del aviso.
        assert settings.AI_SUGGESTION_LABEL == "SUGERENCIA GENERADA POR IA"
        assert "inteligencia artificial" in settings.AI_SUGGESTION_DISCLAIMER
        assert "no constituye una" in settings.AI_SUGGESTION_DISCLAIMER.lower()


class TestCelery:
    def test_la_app_celery_esta_registrada(self) -> None:
        from config import celery_app

        assert celery_app.main == "unicare"

    def test_el_beat_schedule_es_estatico(self) -> None:
        # DEC-11: nada de django-celery-beat (crearia tablas fuera del DER).
        assert "django_celery_beat" not in settings.INSTALLED_APPS

    def test_el_planificador_tiene_una_sola_fuente(self) -> None:
        # `config/celery.py` no debe reasignar el schedule: las settings de
        # Django se leen de forma perezosa y lo pisarian.
        from config import celery_app

        assert celery_app.conf.beat_schedule == settings.CELERY_BEAT_SCHEDULE

    def test_el_worker_lee_la_configuracion_de_django(self) -> None:
        from config import celery_app

        assert celery_app.conf.broker_url == settings.CELERY_BROKER_URL
        assert celery_app.conf.timezone == settings.TIME_ZONE


class TestHealthCheck:
    """El liveness no toca ninguna dependencia, por eso no necesita base."""

    def test_liveness_responde_sin_autenticacion(self) -> None:
        response = APIClient().get("/api/v1/health/")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestEntryPoints:
    @pytest.mark.parametrize("modulo", ["config.wsgi", "config.asgi", "config.urls"])
    def test_los_modulos_de_arranque_importan(self, modulo: str) -> None:
        assert importlib.import_module(modulo) is not None
