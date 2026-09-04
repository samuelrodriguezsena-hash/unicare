"""Tests de `GeminiService` (FASE 9).

NINGUNA llamada real al SDK. El cliente se inyecta como doble, que es
exactamente el proposito de haber confinado la superficie del SDK a `_invoke()`
(C-08): si esa firma cambiara, estos tests seguirian siendo validos.

No requieren PostgreSQL: el servicio no toca la base.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from django.conf import settings
from django.test import override_settings

from apps.core import prompts
from apps.core.exceptions import (
    GeminiNotConfiguredError,
    GeminiResponseError,
    GeminiServiceError,
)
from apps.core.services.gemini import GeminiService, ai_envelope

PRIORIDADES = ["URGENT", "ROUTINE_CONTROL", "POST_OPERATIVE"]


class RespuestaFalsa:
    def __init__(self, text: str) -> None:
        self.text = text


class ClienteFalso:
    """Doble del cliente del SDK: reproduce `client.interactions.create(...)`."""

    def __init__(self, respuesta: Any = None, error: Exception | None = None) -> None:
        self._respuesta = respuesta
        self._error = error
        self.llamadas: list[dict] = []
        self.interactions = self

    def create(self, **kwargs: Any) -> Any:
        self.llamadas.append(kwargs)
        if self._error is not None:
            raise self._error
        return self._respuesta


def servicio(respuesta: Any = None, error: Exception | None = None) -> GeminiService:
    return GeminiService(client=ClienteFalso(respuesta, error))


class TestInvocacion:
    def test_usa_el_modelo_configurado(self) -> None:
        cliente = ClienteFalso(RespuestaFalsa("un resumen"))
        GeminiService(client=cliente).generate_clinical_summary({})

        assert cliente.llamadas[0]["model"] == settings.GEMINI_MODEL

    def test_el_modelo_por_defecto_es_el_documentado(self) -> None:
        assert settings.GEMINI_MODEL == "gemini-3.7-flash"

    def test_envia_el_prompt_como_input(self) -> None:
        cliente = ClienteFalso(RespuestaFalsa("un resumen"))
        GeminiService(client=cliente).generate_clinical_summary({"edad": 46})

        assert "46" in cliente.llamadas[0]["input"]

    def test_un_fallo_del_sdk_se_traduce_a_error_de_dominio(self) -> None:
        # Nunca debe escapar como un 500 con traza.
        with pytest.raises(GeminiServiceError):
            servicio(error=RuntimeError("boom")).generate_clinical_summary({})

    def test_sin_api_key_no_se_intenta_llamar(self) -> None:
        with (
            override_settings(GEMINI_API_KEY=""),
            pytest.raises(GeminiNotConfiguredError),
        ):
            GeminiService().generate_clinical_summary({})

    @pytest.mark.parametrize("atributo", ["text", "output_text", "content"])
    def test_extrae_el_texto_de_los_atributos_habituales(self, atributo: str) -> None:
        # C-08: la forma de la respuesta no es verificable; se prueba defensivo.
        respuesta = type("R", (), {atributo: "contenido"})()
        assert servicio(respuesta).generate_clinical_summary({}) == "contenido"

    def test_acepta_una_respuesta_que_ya_sea_texto(self) -> None:
        assert servicio("contenido").generate_clinical_summary({}) == "contenido"

    def test_una_respuesta_sin_texto_es_error_de_integracion(self) -> None:
        with pytest.raises(GeminiResponseError):
            servicio(object()).generate_clinical_summary({})

    def test_una_respuesta_vacia_es_error_de_integracion(self) -> None:
        with pytest.raises(GeminiResponseError):
            servicio(RespuestaFalsa("   ")).generate_clinical_summary({})


class TestResumenClinico:
    def test_devuelve_el_texto_del_modelo(self) -> None:
        resumen = servicio(
            RespuestaFalsa("  Paciente con...  ")
        ).generate_clinical_summary({})
        assert resumen == "Paciente con..."

    def test_recorta_un_resumen_desmedido(self) -> None:
        largo = "x" * 10_000
        resumen = servicio(RespuestaFalsa(largo)).generate_clinical_summary({})
        assert len(resumen) == 4000


class TestSugerenciaDeTratamiento:
    SALIDA = {
        "familias_farmacologicas": ["Estatinas", "Fibratos"],
        "principios_activos": ["Atorvastatina"],
    }

    def test_devuelve_las_dos_listas(self) -> None:
        resultado = servicio(RespuestaFalsa(json.dumps(self.SALIDA))).suggest_treatment(
            {}
        )
        assert resultado == self.SALIDA

    def test_tolera_el_json_envuelto_en_un_bloque_de_codigo(self) -> None:
        crudo = f"```json\n{json.dumps(self.SALIDA)}\n```"
        resultado = servicio(RespuestaFalsa(crudo)).suggest_treatment({})
        assert resultado["familias_farmacologicas"] == ["Estatinas", "Fibratos"]

    def test_un_json_invalido_es_error_de_integracion(self) -> None:
        # Devolver texto libre como si fuera una sugerencia seria peor.
        with pytest.raises(GeminiResponseError):
            servicio(RespuestaFalsa("Le recomiendo atorvastatina")).suggest_treatment(
                {}
            )

    def test_una_estructura_inesperada_es_error_de_integracion(self) -> None:
        with pytest.raises(GeminiResponseError):
            servicio(RespuestaFalsa('["Estatinas"]')).suggest_treatment({})

    def test_un_campo_que_no_es_lista_es_error_de_integracion(self) -> None:
        crudo = json.dumps({"familias_farmacologicas": "Estatinas"})
        with pytest.raises(GeminiResponseError):
            servicio(RespuestaFalsa(crudo)).suggest_treatment({})

    def test_descarta_elementos_que_no_son_texto(self) -> None:
        crudo = json.dumps(
            {
                "familias_farmacologicas": ["Estatinas", 7, "", None],
                "principios_activos": [],
            }
        )
        resultado = servicio(RespuestaFalsa(crudo)).suggest_treatment({})
        assert resultado["familias_farmacologicas"] == ["Estatinas"]

    def test_acota_el_numero_de_elementos(self) -> None:
        crudo = json.dumps(
            {
                "familias_farmacologicas": [f"F{i}" for i in range(20)],
                "principios_activos": [f"P{i}" for i in range(20)],
            }
        )
        resultado = servicio(RespuestaFalsa(crudo)).suggest_treatment({})
        assert len(resultado["familias_farmacologicas"]) == 5
        assert len(resultado["principios_activos"]) == 8


class TestPrioridadDeCita:
    def test_devuelve_un_valor_del_dominio(self) -> None:
        prioridad = servicio(RespuestaFalsa("URGENT")).prioritize_appointment(
            {}, PRIORIDADES
        )
        assert prioridad == "URGENT"

    @pytest.mark.parametrize("crudo", ["urgent", " Urgent. ", '"URGENT"'])
    def test_normaliza_la_respuesta(self, crudo: str) -> None:
        assert (
            servicio(RespuestaFalsa(crudo)).prioritize_appointment({}, PRIORIDADES)
            == "URGENT"
        )

    def test_un_valor_fuera_del_dominio_es_error(self) -> None:
        # No se inventa una equivalencia ni se guarda tal cual.
        with pytest.raises(GeminiResponseError):
            servicio(RespuestaFalsa("MUY URGENTE")).prioritize_appointment(
                {}, PRIORIDADES
            )


class TestEnvoltorioDeIa:
    def test_toda_salida_lleva_etiqueta_y_advertencia(self) -> None:
        sobre = ai_envelope({"summary": "x"})
        assert sobre["label"] == "SUGERENCIA GENERADA POR IA"
        assert "inteligencia artificial" in sobre["disclaimer"]
        assert "prescripcion" in sobre["disclaimer"]

    def test_nace_pendiente_de_validacion(self) -> None:
        # El flujo de aprobacion nunca da nada por aprobado automaticamente.
        assert ai_envelope({})["status"] == "PENDIENTE_DE_VALIDACION"

    def test_declara_con_que_prompt_y_modelo_se_genero(self) -> None:
        sobre = ai_envelope({})
        assert sobre["prompt_version"] == prompts.PROMPT_VERSION
        assert sobre["model"] == settings.GEMINI_MODEL


class TestPrompts:
    def test_son_deterministas(self) -> None:
        contexto = {"b": 2, "a": 1}
        assert prompts.clinical_summary(contexto) == prompts.clinical_summary(
            {"a": 1, "b": 2}
        )

    def test_declaran_que_la_ia_no_es_autoridad_clinica(self) -> None:
        for prompt in (
            prompts.clinical_summary({}),
            prompts.treatment_suggestion({}),
            prompts.appointment_priority({}, PRIORIDADES),
        ):
            assert "NO eres una autoridad clinica" in prompt
            assert "no prescribes" in prompt

    def test_el_de_tratamiento_prohibe_dar_posologia(self) -> None:
        prompt = prompts.treatment_suggestion({})
        assert "No indiques dosis" in prompt
        assert "NO una prescripcion" in prompt

    def test_el_de_prioridad_acota_el_dominio(self) -> None:
        prompt = prompts.appointment_priority({}, PRIORIDADES)
        for valor in PRIORIDADES:
            assert valor in prompt

    def test_el_de_resumen_prohibe_inventar(self) -> None:
        assert "No anadas datos" in prompts.clinical_summary({})


class TestConstruccionDelCliente:
    """La frontera con el SDK (C-08): lo unico que rompe si su firma cambia."""

    def test_construye_el_cliente_del_sdk_cuando_hay_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys
        import types

        construidos: list[str] = []

        class ClienteDelSdk:
            def __init__(self) -> None:
                construidos.append("si")

        falso_genai = types.SimpleNamespace(Client=ClienteDelSdk)
        falso_google = types.ModuleType("google")
        falso_google.genai = falso_genai
        monkeypatch.setitem(sys.modules, "google", falso_google)
        monkeypatch.setitem(sys.modules, "google.genai", falso_genai)

        with override_settings(GEMINI_API_KEY="una-clave"):
            cliente = GeminiService()._get_client()

        assert construidos == ["si"]
        assert isinstance(cliente, ClienteDelSdk)

    def test_la_clave_no_se_pasa_como_argumento(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Asi no aparece en trazas ni en `repr()`; el SDK la lee del entorno."""
        import sys
        import types

        recibidos: list[dict] = []

        class ClienteDelSdk:
            def __init__(self, **kwargs: Any) -> None:
                recibidos.append(kwargs)

        falso_genai = types.SimpleNamespace(Client=ClienteDelSdk)
        falso_google = types.ModuleType("google")
        falso_google.genai = falso_genai
        monkeypatch.setitem(sys.modules, "google", falso_google)
        monkeypatch.setitem(sys.modules, "google.genai", falso_genai)

        with override_settings(GEMINI_API_KEY="una-clave"):
            GeminiService()._get_client()

        assert recibidos == [{}]
