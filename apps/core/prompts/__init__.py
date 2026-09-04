"""Prompts enviados a Gemini.

Estan aqui, versionados y separados del codigo que los envia, para que puedan
revisarse sin leer la logica de integracion.

Tres reglas que cumplen todos:

  1. **Estructurados y deterministas.** Plantillas fijas, sin nada aleatorio, y
     con el formato de salida declarado de forma explicita. La misma entrada
     produce el mismo prompt.
  2. **Alcance acotado.** Se pide apoyo, no decision. Ningun prompt pide un
     diagnostico, una prescripcion ni una decision clinica.
  3. **Salida verificable.** Se exige un formato que el servicio pueda validar
     antes de devolver nada al cliente.
"""

from __future__ import annotations

import json
from typing import Any

# Se incrementa al cambiar cualquier plantilla. Permite saber con que version
# se genero un resumen si alguna vez hay que auditarlo.
PROMPT_VERSION = "1.0"

_PREAMBULO = (
    "Eres un asistente de apoyo documental para profesionales clinicos en una "
    "plataforma de seguimiento de pacientes oncologicos.\n"
    "NO eres una autoridad clinica. No emites diagnosticos, no prescribes y no "
    "tomas decisiones medicas. Tu salida es material preliminar que un "
    "profesional revisara.\n"
    "Responde unicamente en espanol.\n"
)


def _bloque_json(datos: Any) -> str:
    """Serializa el contexto de forma estable.

    `sort_keys` y `ensure_ascii=False` garantizan que el mismo contexto produce
    exactamente el mismo texto: sin eso, el prompt cambiaria entre ejecuciones
    y la salida dejaria de ser reproducible.
    """
    return json.dumps(datos, ensure_ascii=False, sort_keys=True, indent=2)


def clinical_summary(historial: dict[str, Any]) -> str:
    """Resumen narrativo del historial clinico estructurado de un paciente."""
    return (
        f"{_PREAMBULO}\n"
        "TAREA: redacta un resumen narrativo conciso del historial clinico que "
        "aparece mas abajo.\n\n"
        "REGLAS:\n"
        "- Usa exclusivamente la informacion proporcionada. No anadas datos, "
        "cifras, farmacos ni conclusiones que no esten en ella.\n"
        "- Si un dato no consta, omitelo; no lo supongas.\n"
        "- Maximo 200 palabras, en prosa continua y en pasado.\n"
        "- No incluyas recomendaciones, ni pronosticos, ni pasos a seguir.\n"
        "- Devuelve unicamente el texto del resumen, sin titulos ni vinetas.\n\n"
        "HISTORIAL CLINICO ESTRUCTURADO:\n"
        f"{_bloque_json(historial)}\n"
    )


def treatment_suggestion(contexto: dict[str, Any]) -> str:
    """Familias farmacologicas y principios activos, como sugerencia."""
    return (
        f"{_PREAMBULO}\n"
        "TAREA: a partir de la patologia y el contexto clinico de mas abajo, "
        "enumera familias farmacologicas y principios activos que un "
        "profesional podria considerar.\n\n"
        "REGLAS:\n"
        "- Es una lista de opciones a revisar, NO una prescripcion.\n"
        "- No indiques dosis, posologia, via ni duracion.\n"
        "- No afirmes que ningun tratamiento sea adecuado para este paciente.\n"
        "- Como maximo 5 familias y 8 principios activos.\n"
        "- Si la informacion es insuficiente, devuelve listas vacias.\n\n"
        "FORMATO DE SALIDA: unicamente un objeto JSON valido, sin texto "
        "alrededor y sin marcas de codigo, con exactamente estas dos claves:\n"
        '{"familias_farmacologicas": ["..."], "principios_activos": ["..."]}\n\n'
        "CONTEXTO CLINICO:\n"
        f"{_bloque_json(contexto)}\n"
    )


def appointment_priority(contexto: dict[str, Any], valores: list[str]) -> str:
    """Prioridad sugerida para una cita, dentro de un dominio cerrado."""
    opciones = ", ".join(valores)
    return (
        f"{_PREAMBULO}\n"
        "TAREA: sugiere una prioridad de atencion para la solicitud de cita "
        "descrita mas abajo.\n\n"
        "REGLAS:\n"
        "- Es una priorizacion sugerida para ordenar la agenda, NO una "
        "valoracion clinica ni una decision de triaje.\n"
        f"- Responde con UNA sola de estas opciones: {opciones}\n"
        "- Devuelve solo esa palabra, sin explicacion, comillas ni puntuacion.\n"
        "- Ante la duda, elige la opcion menos urgente.\n\n"
        "SOLICITUD DE CITA:\n"
        f"{_bloque_json(contexto)}\n"
    )
