"""Tests de los validadores reutilizables de `core`.

No necesitan base de datos: son funciones puras.
"""

from __future__ import annotations

import pytest
from django.core.exceptions import ValidationError
from django.test import override_settings

from apps.core.validators import (
    validate_identification_number,
    validate_import_file_extension,
    validate_required_fields,
)


class TestNumeroDeIdentificacion:
    @pytest.mark.parametrize(
        "valor",
        ["1098765432", "CC-1098765432", "A1", "12.345.678", "X" * 50],
    )
    def test_acepta_formatos_razonables(self, valor: str) -> None:
        assert validate_identification_number(valor) == valor

    def test_recorta_espacios_de_los_extremos(self) -> None:
        assert validate_identification_number("  1098765432  ") == "1098765432"

    def test_no_altera_el_dato_del_paciente(self) -> None:
        # Ni mayusculas ni separadores internos: cambiarlos seria corromperlo.
        assert validate_identification_number("cc-98x") == "cc-98x"

    @pytest.mark.parametrize("valor", ["", "   ", None])
    def test_rechaza_lo_vacio(self, valor: str | None) -> None:
        with pytest.raises(ValidationError):
            validate_identification_number(valor)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "valor",
        ["1 098 765", "A", "'; DROP TABLE patient;--", "12345678901234567890" * 3],
    )
    def test_rechaza_lo_invalido(self, valor: str) -> None:
        with pytest.raises(ValidationError):
            validate_identification_number(valor)

    def test_el_patron_es_configurable(self) -> None:
        # DEC-17: el DER no define el formato, asi que no se impone uno rigido.
        with override_settings(IDENTIFICATION_NUMBER_PATTERN=r"^\d{10}$"):
            assert validate_identification_number("1098765432") == "1098765432"
            with pytest.raises(ValidationError):
                validate_identification_number("CC-123")


class TestCamposRequeridos:
    def test_pasa_cuando_estan_todos(self) -> None:
        validate_required_fields(
            {"identificacion": "123", "nombre": "Ana"}, ["identificacion", "nombre"]
        )

    @pytest.mark.parametrize("vacio", ["", "   ", None])
    def test_falla_cuando_alguno_esta_vacio(self, vacio: str | None) -> None:
        with pytest.raises(ValidationError) as exc:
            validate_required_fields({"nombre": vacio}, ["nombre"])
        assert "nombre" in str(exc.value)

    def test_el_mensaje_nombra_todos_los_que_faltan(self) -> None:
        with pytest.raises(ValidationError) as exc:
            validate_required_fields({}, ["identificacion", "nombre"])
        mensaje = str(exc.value)
        assert "identificacion" in mensaje
        assert "nombre" in mensaje


class TestFormatoDeImportacion:
    @pytest.mark.parametrize(
        ("nombre", "esperado"),
        [
            ("pacientes.csv", ".csv"),
            ("pacientes.CSV", ".csv"),
            ("carga.xlsx", ".xlsx"),
            ("informe.final.xlsx", ".xlsx"),
        ],
    )
    def test_acepta_csv_y_xlsx(self, nombre: str, esperado: str) -> None:
        assert validate_import_file_extension(nombre) == esperado

    @pytest.mark.parametrize("nombre", ["datos.xls", "datos.txt", "datos", ""])
    def test_rechaza_el_resto(self, nombre: str) -> None:
        with pytest.raises(ValidationError):
            validate_import_file_extension(nombre)
