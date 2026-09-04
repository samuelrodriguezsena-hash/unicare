"""Cobertura de la politica de permisos (FASE 13).

Los tests de cada app comprueban que SUS endpoints exigen autenticacion. Este
modulo comprueba lo que ninguno puede: que **no queda ni uno suelto**.

Recorre el URLconf entero y verifica que todo endpoint que no sea publico de
forma deliberada rechaza a un anonimo. Un endpoint nuevo sin permisos hace
fallar este test aunque nadie escriba un test especifico para el.

Requiere PostgreSQL: algunas vistas consultan la base antes de decidir.
"""

from __future__ import annotations

import pytest
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.test import APIClient

from apps.core.permissions import IsAuthenticatedAndActive, describe_policy
from tests.db import saltar_si_no_hay_postgresql

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db

# Endpoints publicos DELIBERADAMENTE. Cualquier otro debe exigir autenticacion.
PUBLICOS = {
    # Sin ellos no habria forma de obtener el primer token.
    "core:token-obtain",
    "core:token-refresh",
    "core:token-verify",
    # Las sondas las consulta el orquestador, que no tiene credenciales.
    "core:health",
    "core:health-ready",
}

METODOS = ("get", "post", "patch", "delete")


def _rutas(
    resolver=None, prefijo: str = "", espacio: str = ""
) -> list[tuple[str, str]]:
    """Devuelve (nombre_completo, url) de todas las rutas con nombre."""
    resolver = resolver or get_resolver()
    encontradas: list[tuple[str, str]] = []

    for patron in resolver.url_patterns:
        if isinstance(patron, URLResolver):
            encontradas.extend(
                _rutas(
                    patron,
                    prefijo + str(patron.pattern),
                    patron.namespace or espacio,
                )
            )
        elif isinstance(patron, URLPattern) and patron.name:
            nombre = f"{espacio}:{patron.name}" if espacio else patron.name
            encontradas.append((nombre, prefijo + str(patron.pattern)))
    return encontradas


def _url_concreta(patron: str) -> str:
    """Sustituye los parametros de la ruta por un valor cualquiera."""
    import re

    url = re.sub(r"<int:[^>]+>", "1", patron)
    url = re.sub(r"<[^>]+>", "1", url)
    return "/" + url.lstrip("^/").replace("$", "")


RUTAS = _rutas()
PROTEGIDAS = [(n, p) for n, p in RUTAS if n not in PUBLICOS]


class TestInventarioDeRutas:
    def test_se_encontraron_rutas(self) -> None:
        # Si el recorrido del URLconf se rompiera, el resto de este modulo
        # pasaria en vacio sin comprobar nada.
        assert len(RUTAS) > 20

    def test_todas_las_publicas_existen(self) -> None:
        nombres = {n for n, _ in RUTAS}
        assert PUBLICOS <= nombres

    def test_hay_endpoints_protegidos_en_las_cinco_apps(self) -> None:
        espacios = {n.split(":")[0] for n, _ in PROTEGIDAS if ":" in n}
        assert espacios == {
            "core",
            "people",
            "medications",
            "appointments",
            "massive_load",
        }


@pytest.mark.parametrize(
    ("nombre", "patron"), PROTEGIDAS, ids=[n for n, _ in PROTEGIDAS]
)
class TestTodoEndpointExigeAutenticacion:
    def test_un_anonimo_nunca_recibe_una_respuesta_util(
        self, nombre: str, patron: str
    ) -> None:
        """Ni 2xx ni 3xx: o 401, o el metodo no esta permitido."""
        cliente = APIClient()
        url = _url_concreta(patron)

        for metodo in METODOS:
            respuesta = getattr(cliente, metodo)(url)
            assert respuesta.status_code in {401, 405}, (
                f"{nombre} ({metodo.upper()} {url}) respondio "
                f"{respuesta.status_code} a un anonimo"
            )


class TestPoliticaVigente:
    def test_no_hay_roles_y_esta_documentado(self) -> None:
        # C-03: el DER no define roles en USER.
        politica = describe_policy()
        assert politica["roles"] is False
        assert "DECISIONS" in politica["motivo"]

    def test_la_politica_exige_usuario_activo(self) -> None:
        from types import SimpleNamespace

        permiso = IsAuthenticatedAndActive()
        activo = SimpleNamespace(is_authenticated=True, is_active=True)
        inactivo = SimpleNamespace(is_authenticated=True, is_active=False)
        anonimo = SimpleNamespace(is_authenticated=False, is_active=True)

        assert permiso.has_permission(SimpleNamespace(user=activo), None) is True
        assert permiso.has_permission(SimpleNamespace(user=inactivo), None) is False
        assert permiso.has_permission(SimpleNamespace(user=anonimo), None) is False
        assert permiso.has_permission(SimpleNamespace(user=None), None) is False

    def test_la_logica_de_permisos_esta_separada_del_negocio(self) -> None:
        """Requisito explicito de la documentacion.

        Las clases de permiso viven solo en `apps/core/permissions.py`; las
        vistas las referencian, no las definen.
        """
        from pathlib import Path

        for fichero in Path("apps").rglob("*.py"):
            if fichero.name == "permissions.py":
                continue
            texto = fichero.read_text(encoding="utf-8")
            assert "class.*BasePermission" not in texto
            assert "def has_permission" not in texto
