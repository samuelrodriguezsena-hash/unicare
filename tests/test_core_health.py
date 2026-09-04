"""Tests de los health checks.

El liveness no necesita base. El readiness SI: su razon de ser es comprobar
dependencias reales, y verificarlo con todo mockeado no probaria nada.
"""

from __future__ import annotations

import pytest
from rest_framework.test import APIClient

from apps.core.views import ReadinessView
from tests.db import skipif_sin_postgresql

LIVENESS = "/api/v1/health/"
READINESS = "/api/v1/health/ready/"


class TestLiveness:
    def test_responde_sin_autenticacion(self) -> None:
        respuesta = APIClient().get(LIVENESS)
        assert respuesta.status_code == 200
        assert respuesta.json() == {"status": "ok"}

    def test_sigue_respondiendo_aunque_la_base_este_caida(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Un liveness que consulta la base se cae cuando la base se cae.

        Eso es justo lo contrario de lo que debe hacer: sacaria el proceso del
        balanceador por un problema que no es suyo.
        """
        from django.db import connections

        def explota(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("El liveness no debe tocar PostgreSQL")

        monkeypatch.setattr(connections["default"], "cursor", explota)
        assert APIClient().get(LIVENESS).status_code == 200


class TestReadinessSinBase:
    def test_reporta_no_disponible_si_postgresql_no_responde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ReadinessView, "_check_database", staticmethod(lambda: False)
        )
        monkeypatch.setattr(ReadinessView, "_check_cache", staticmethod(lambda: True))

        respuesta = APIClient().get(READINESS)
        assert respuesta.status_code == 503
        assert respuesta.json()["status"] == "not-ready"
        assert respuesta.json()["checks"]["database"] is False

    def test_reporta_no_disponible_si_redis_no_responde(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            ReadinessView, "_check_database", staticmethod(lambda: True)
        )
        monkeypatch.setattr(ReadinessView, "_check_cache", staticmethod(lambda: False))

        respuesta = APIClient().get(READINESS)
        assert respuesta.status_code == 503
        assert respuesta.json()["checks"]["cache"] is False

    def test_el_check_de_base_devuelve_false_ante_un_fallo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from django.db import connections

        def explota(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("conexion perdida")

        monkeypatch.setattr(connections["default"], "cursor", explota)
        assert ReadinessView._check_database() is False

    def test_el_check_de_cache_devuelve_false_ante_un_fallo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from django.core.cache import cache

        def explota(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("redis caido")

        monkeypatch.setattr(cache, "set", explota)
        assert ReadinessView._check_cache() is False


@skipif_sin_postgresql()
class TestReadinessConBase:
    """Comprobacion de verdad contra PostgreSQL."""

    def test_responde_listo_con_las_dependencias_arriba(self, db: object) -> None:
        respuesta = APIClient().get(READINESS)
        assert respuesta.status_code == 200
        assert respuesta.json() == {
            "status": "ready",
            "checks": {"database": True, "cache": True},
        }

    def test_el_check_de_base_consulta_de_verdad(self, db: object) -> None:
        assert ReadinessView._check_database() is True
