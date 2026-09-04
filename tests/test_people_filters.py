"""Tests unitarios del calculo de edades.

Sin base de datos: `restar_anios` es una funcion pura, y su unico caso dificil
es el 29 de febrero.
"""

from __future__ import annotations

from datetime import date

import pytest

from apps.people.filters import restar_anios


@pytest.mark.parametrize(
    ("fecha", "anios", "esperado"),
    [
        (date(2026, 8, 31), 0, date(2026, 8, 31)),
        (date(2026, 8, 31), 46, date(1980, 8, 31)),
        (date(2026, 1, 1), 100, date(1926, 1, 1)),
        # 2024 es bisiesto y 2023 no: el 29 de febrero no existe en destino.
        (date(2024, 2, 29), 1, date(2023, 2, 28)),
        (date(2024, 2, 29), 4, date(2020, 2, 29)),
    ],
)
def test_restar_anios(fecha: date, anios: int, esperado: date) -> None:
    assert restar_anios(fecha, anios) == esperado
