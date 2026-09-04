"""Integracion con Gemini.

Unica capa del proyecto autorizada a hablar con el SDK. Ni modelos, ni
serializers, ni vistas invocan a Gemini: siempre pasan por aqui.

REGLA CLINICA: Gemini no es una autoridad clinica. Toda salida de este modulo
es una SUGERENCIA que requiere validacion profesional, y viaja siempre
acompanada de su etiqueta y su advertencia (`ai_envelope`).

C-08 (docs/DECISIONS.md): no ha sido posible verificar contra la documentacion
oficial del SDK que `client.interactions.create(...)` y el identificador
`gemini-3.7-flash` sean su superficie real. Se usa el patron EXACTAMENTE como
lo indica la documentacion normativa del proyecto, confinado a `_invoke()`. Si
la firma resultara distinta, el ajuste se limita a ese metodo: ni los
servicios, ni las vistas, ni los tests dependen de ella.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import sentry_sdk
from django.conf import settings

from apps.core import prompts
from apps.core.exceptions import (
    GeminiNotConfiguredError,
    GeminiResponseError,
    GeminiServiceError,
)

logger = logging.getLogger(__name__)

# Tope defensivo del resumen. El prompt pide 200 palabras; si el modelo se
# excede, se corta antes de persistir en lugar de guardar algo desmedido.
MAX_SUMMARY_CHARS = 4000

# Algunos modelos envuelven el JSON en un bloque de codigo pese a pedirles que
# no lo hagan. Se retira antes de parsear.
_VALLA_DE_CODIGO = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def ai_envelope(payload: dict[str, Any]) -> dict[str, Any]:
    """Envuelve una salida de IA con su etiqueta y su advertencia.

    NINGUNA salida de Gemini debe llegar al cliente sin pasar por aqui.

    `status` refleja el flujo de aprobacion: lo que produce la IA nace siempre
    pendiente de validacion. Para la sugerencia de tratamiento no hay donde
    persistir ese estado (C-06), asi que es informativo.
    """
    return {
        "label": settings.AI_SUGGESTION_LABEL,
        "disclaimer": settings.AI_SUGGESTION_DISCLAIMER,
        "status": "PENDIENTE_DE_VALIDACION",
        "prompt_version": prompts.PROMPT_VERSION,
        "model": settings.GEMINI_MODEL,
        **payload,
    }


class GeminiService:
    """Servicio de apoyo documental basado en Gemini."""

    def __init__(self, client: Any | None = None) -> None:
        # Inyectable: los tests sustituyen el cliente sin tocar el SDK.
        self._client = client

    # ------------------------------------------------------------------
    # Frontera con el SDK. TODO lo especifico de Gemini vive aqui.
    # ------------------------------------------------------------------
    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        if not settings.GEMINI_API_KEY:
            raise GeminiNotConfiguredError

        from google import genai

        # El SDK toma GEMINI_API_KEY del entorno. La clave no se pasa como
        # argumento para que no aparezca en trazas ni en repr().
        self._client = genai.Client()
        return self._client

    def _invoke(self, prompt: str) -> str:
        """Envia un prompt y devuelve el texto de la respuesta.

        UNICO punto del proyecto que toca el SDK de Gemini (C-08).
        """
        try:
            respuesta = self._get_client().interactions.create(
                model=settings.GEMINI_MODEL,
                input=prompt,
            )
        except GeminiNotConfiguredError:
            raise
        except Exception as exc:
            # El SDK no documenta una jerarquia de excepciones estable, asi que
            # aqui si esta justificado capturar de forma amplia: cualquier
            # fallo suyo debe convertirse en un error de dominio y no escapar
            # como un 500 con traza.
            logger.error("Fallo al invocar Gemini")
            sentry_sdk.capture_exception(exc)
            raise GeminiServiceError from exc

        return self._extract_text(respuesta)

    @staticmethod
    def _extract_text(respuesta: Any) -> str:
        """Extrae el texto de la respuesta del SDK.

        Defensivo por el mismo motivo que `_invoke`: la forma exacta del objeto
        de respuesta no es verificable (C-08). Se prueban los atributos
        habituales antes de recurrir a la conversion a texto.
        """
        for atributo in ("text", "output_text", "content"):
            valor = getattr(respuesta, atributo, None)
            if isinstance(valor, str) and valor.strip():
                return valor.strip()

        if isinstance(respuesta, str) and respuesta.strip():
            return respuesta.strip()

        raise GeminiResponseError(
            "La respuesta del modelo no contiene texto utilizable."
        )

    # ------------------------------------------------------------------
    # Metodos especializados
    # ------------------------------------------------------------------
    def generate_clinical_summary(self, historial: dict[str, Any]) -> str:
        """Resumen narrativo del historial clinico estructurado.

        No hace falta comprobar aqui que el texto no este vacio: `_extract_text`
        ya rechaza una respuesta sin contenido utilizable.
        """
        return self._invoke(prompts.clinical_summary(historial))[:MAX_SUMMARY_CHARS]

    def suggest_treatment(self, contexto: dict[str, Any]) -> dict[str, list[str]]:
        """Familias farmacologicas y principios activos a considerar.

        La salida se valida antes de devolverse: si no es el JSON esperado, es
        un error de integracion y NO un resultado. Devolver texto libre como si
        fuera una sugerencia estructurada seria peor que fallar.
        """
        crudo = self._invoke(prompts.treatment_suggestion(contexto))
        datos = self._parse_json(crudo)

        if not isinstance(datos, dict):
            raise GeminiResponseError(
                "El modelo no devolvio un objeto JSON con la estructura pedida."
            )

        return {
            "familias_farmacologicas": self._lista_de_textos(
                datos.get("familias_farmacologicas"), limite=5
            ),
            "principios_activos": self._lista_de_textos(
                datos.get("principios_activos"), limite=8
            ),
        }

    def prioritize_appointment(
        self, contexto: dict[str, Any], valores_admitidos: list[str]
    ) -> str:
        """Prioridad sugerida, siempre dentro del dominio cerrado indicado.

        Si el modelo responde algo fuera de ese dominio, es un error de
        integracion: no se inventa una equivalencia ni se guarda tal cual.
        """
        crudo = self._invoke(prompts.appointment_priority(contexto, valores_admitidos))
        candidato = crudo.strip().strip(".\"'").upper()

        if candidato not in valores_admitidos:
            logger.warning("Gemini devolvio una prioridad fuera del dominio")
            raise GeminiResponseError(
                "El modelo devolvio una prioridad que no esta entre las " "admitidas."
            )
        return candidato

    # ------------------------------------------------------------------
    # Validacion de la respuesta
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_json(crudo: str) -> Any:
        limpio = _VALLA_DE_CODIGO.sub("", crudo).strip()
        try:
            return json.loads(limpio)
        except ValueError as exc:
            raise GeminiResponseError("El modelo no devolvio un JSON valido.") from exc

    @staticmethod
    def _lista_de_textos(valor: Any, limite: int) -> list[str]:
        """Normaliza una lista de cadenas, descartando lo que no lo sea."""
        if not isinstance(valor, list):
            raise GeminiResponseError(
                "El modelo no devolvio listas en los campos esperados."
            )
        elementos = [
            item.strip() for item in valor if isinstance(item, str) and item.strip()
        ]
        return elementos[:limite]
