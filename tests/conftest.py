"""Configuracion comun de la suite.

Contiene una salvaguarda importante: **ningun test puede salir a la red**.

La documentacion lo exige de forma explicita ("los tests NO deben realizar
llamadas reales a la API externa", "no depender de servicios externos reales").
Confiar en que cada test recuerde mockear no basta: un `respx.mock` olvidado, un
import nuevo o una dependencia que llame a casa pasarian desapercibidos, harian
la suite lenta y no determinista, y en el peor caso mandarian datos de prueba a
un tercero.

Aqui se bloquea a nivel de socket, que es la unica capa por la que tienen que
pasar todos.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest

# Loopback: PostgreSQL y cualquier servicio local de desarrollo.
ANFITRIONES_PERMITIDOS = frozenset(
    # No es un bind: es la lista de destinos a los que SI se puede conectar.
    {"127.0.0.1", "::1", "localhost", "0.0.0.0"}  # noqa: S104
)

_connect_original = socket.socket.connect


class RedProhibidaError(RuntimeError):
    """Un test ha intentado abrir una conexion de red real."""


def _anfitrion(direccion: Any) -> str:
    if isinstance(direccion, tuple) and direccion:
        return str(direccion[0])
    return str(direccion)


def _connect_vigilado(self: socket.socket, direccion: Any, *args: Any) -> Any:
    destino = _anfitrion(direccion)
    if destino not in ANFITRIONES_PERMITIDOS:
        raise RedProhibidaError(
            f"Un test intento conectar con {destino!r}. La suite no puede salir "
            "a la red: mockea la integracion (respx para httpx, un doble para "
            "el SDK de Gemini). Ver tests/conftest.py."
        )
    return _connect_original(self, direccion, *args)


@pytest.fixture(autouse=True, scope="session")
def _sin_red() -> Iterator[None]:
    """Bloquea las conexiones salientes durante toda la sesion."""
    socket.socket.connect = _connect_vigilado  # type: ignore[method-assign]
    try:
        yield
    finally:
        socket.socket.connect = _connect_original  # type: ignore[method-assign]
