"""Deteccion de PostgreSQL para los tests que lo necesitan.

La suite debe poder ejecutarse sin infraestructura. Los modulos que si
requieren base la comprueban con `saltar_si_no_hay_postgresql()`, que salta el
modulo entero en tiempo de recoleccion.

ATENCION: que un modulo se salte NO es lo mismo que que pase.
"""

from __future__ import annotations

import psycopg
import pytest
from django.conf import settings


def hay_postgresql() -> bool:
    """Indica si el PostgreSQL configurado acepta conexiones."""
    db = settings.DATABASES["default"]
    try:
        with psycopg.connect(
            host=db["HOST"] or "localhost",
            port=db["PORT"] or 5432,
            user=db["USER"],
            password=db["PASSWORD"],
            dbname="postgres",
            connect_timeout=3,
        ):
            return True
    except psycopg.Error:
        return False


def saltar_si_no_hay_postgresql() -> None:
    if not hay_postgresql():
        pytest.skip(
            "No hay PostgreSQL accesible; este modulo queda SIN verificar. "
            "Levantalo con `docker compose up -d db` o ver "
            "docs/DEV_POSTGRES_SIN_DOCKER.md.",
            allow_module_level=True,
        )


def skipif_sin_postgresql() -> pytest.MarkDecorator:
    """Marca para tests SUELTOS que necesitan base dentro de un modulo mixto.

    `saltar_si_no_hay_postgresql()` salta el modulo entero y no sirve cuando
    solo algunos tests necesitan base. Ademas, la fixture `db` de pytest-django
    se resuelve ANTES del cuerpo del test, asi que un `skip` alli dentro llega
    tarde: tiene que evaluarse en tiempo de recoleccion, como hace esta marca.
    """
    return pytest.mark.skipif(
        not hay_postgresql(),
        reason=(
            "No hay PostgreSQL accesible; este test queda SIN verificar. "
            "Ver docs/DEV_POSTGRES_SIN_DOCKER.md."
        ),
    )
