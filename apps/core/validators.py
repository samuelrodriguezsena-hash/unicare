"""Validadores reutilizables.

Se usan tanto desde los serializers de la API como desde la carga masiva, para
que un dato rechazado por un camino lo sea tambien por el otro.

NOTA IMPORTANTE SOBRE EL NUMERO DE IDENTIFICACION: ni el DER ni la documentacion
funcional definen su formato. No se inventa uno rigido: el patron es
configurable y su valor por defecto solo descarta lo que es inequivocamente
invalido (vacio, espacios internos, simbolos raros). Ver DEC-17.
"""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError

# Formatos que la documentacion normativa exige soportar en la carga masiva.
FORMATOS_DE_IMPORTACION: frozenset[str] = frozenset({".csv", ".xlsx"})

_PATRON_IDENTIFICACION_POR_DEFECTO = r"^[A-Za-z0-9][A-Za-z0-9.\-]{1,49}$"


def _patron_identificacion() -> re.Pattern[str]:
    patron = getattr(
        settings, "IDENTIFICATION_NUMBER_PATTERN", _PATRON_IDENTIFICACION_POR_DEFECTO
    )
    return re.compile(patron)


def validate_identification_number(valor: str) -> str:
    """Valida y normaliza un numero de identificacion.

    Normaliza unicamente los espacios de los extremos. NO cambia mayusculas ni
    elimina separadores internos: eso alteraria el dato del paciente.
    """
    if valor is None or not str(valor).strip():
        raise ValidationError("El numero de identificacion es obligatorio.")

    limpio = str(valor).strip()
    if not _patron_identificacion().match(limpio):
        raise ValidationError(
            "El numero de identificacion tiene un formato invalido: "
            "se admiten letras, digitos, puntos y guiones (2 a 50 caracteres)."
        )
    return limpio


def validate_required_fields(
    datos: dict[str, Any], obligatorios: list[str] | tuple[str, ...]
) -> None:
    """Comprueba que estan presentes y no vacios todos los campos indicados.

    Pensado para la validacion fila a fila de la carga masiva, donde el mensaje
    debe nombrar exactamente que falta.
    """
    faltan = [
        campo
        for campo in obligatorios
        if datos.get(campo) is None or not str(datos.get(campo)).strip()
    ]
    if faltan:
        raise ValidationError(
            "Faltan datos requeridos: " + ", ".join(sorted(faltan)) + "."
        )


def validate_import_file_extension(nombre: str) -> str:
    """Valida la extension de un archivo de carga masiva.

    Devuelve la extension normalizada en minusculas, que es lo que se guarda en
    `IMPORT_BATCH.source_file_type`.
    """
    if not nombre or "." not in nombre:
        raise ValidationError("El archivo debe tener extension .csv o .xlsx.")

    extension = "." + nombre.rsplit(".", 1)[-1].lower()
    if extension not in FORMATOS_DE_IMPORTACION:
        admitidas = ", ".join(sorted(FORMATOS_DE_IMPORTACION))
        raise ValidationError(
            f"Formato de archivo no admitido: {extension}. Se admiten: {admitidas}."
        )
    return extension
