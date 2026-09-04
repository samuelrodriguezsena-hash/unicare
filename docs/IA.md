# Integración con Gemini

Apoyo documental para profesionales clínicos. **Gemini no es una autoridad clínica**: toda
salida es una sugerencia preliminar que requiere validación profesional, y así se etiqueta.

## Endpoints

| Método | Ruta | Persiste | Descripción |
|---|---|---|---|
| POST | `/api/v1/patients/{id}/ai-summary/` | Sí (caché) | Resumen narrativo del historial |
| POST | `/api/v1/treatment-suggestions/` | **No** | Familias farmacológicas y principios activos |

La priorización de citas (`prioritize_appointment`) está implementada en el servicio y se
conecta a su endpoint en la **FASE 10**.

## Envoltorio obligatorio

**Ninguna salida de Gemini llega al cliente sin pasar por `ai_envelope()`.** Todas incluyen:

```json
{
  "label": "SUGERENCIA GENERADA POR IA",
  "disclaimer": "Esta informacion es una sugerencia generada por inteligencia artificial y requiere validacion por parte de un profesional clinico. No constituye una prescripcion ni una decision medica.",
  "status": "PENDIENTE_DE_VALIDACION",
  "prompt_version": "1.0",
  "model": "gemini-3.7-flash"
}
```

`status` nunca nace aprobado: el flujo de aprobación no da nada por validado automáticamente.
`prompt_version` y `model` permiten saber con qué se generó un resumen si hay que auditarlo.

## Resumen clínico

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/patients/42/ai-summary/
```

```
Paciente → historial estructurado → ClinicalSummaryService → Gemini → resumen → API
```

Se persiste en `CLINICAL_HISTORY.last_ai_summary` y `last_ai_summary_at`. Es una **caché del
último resumen**, no un resumen aprobado: el DER no define ningún estado de aprobación para él
(C-06).

## Sugerencia de tratamiento

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"patient_pathology": 7}' http://localhost:8000/api/v1/treatment-suggestions/
```

Parte de una patología **ya registrada** en el historial del paciente: no se aceptan nombres
sueltos, que permitirían pedir sugerencias sobre cualquier cosa.

```json
{
  "label": "SUGERENCIA GENERADA POR IA",
  "pathology_name": "Carcinoma ductal",
  "familias_farmacologicas": ["Antraciclinas"],
  "principios_activos": ["Doxorrubicina"],
  "persisted": false
}
```

**No se persiste** (C-06 / DEC-07): el DER no define columna ni tabla donde guardarla, ni su
estado de aprobación, y no se crean tablas arbitrarias. El acto de aprobación es que un
profesional decida crear un `TREATMENT_PLAN_MEDICATION` a partir de ella.

> **Limitación conocida:** no queda historial de sugerencias rechazadas.

## Privacidad

Sólo se envía a Gemini lo clínicamente pertinente. **No se envían identificación, teléfono,
email, dirección ni apellidos**: el modelo no necesita identificar al paciente para redactar un
resumen. Hay tests que fallan si alguno de esos datos aparece en el contexto.

El historial se acota (30 entradas, 20 notas): más volumen no mejora el resumen y sí aumenta el
coste y la exposición de datos clínicos.

## Prompts

Versionados en `apps/core/prompts/`, separados del código que los envía para que puedan
revisarse sin leer la integración. Los tres cumplen:

1. **Deterministas** — plantillas fijas y contexto serializado con `sort_keys`: la misma entrada
   produce exactamente el mismo prompt.
2. **Alcance acotado** — piden apoyo, no decisión. Declaran explícitamente que el modelo no es
   autoridad clínica, no diagnostica, no prescribe y no decide.
3. **Salida verificable** — declaran el formato exacto para poder validarlo.

El de tratamiento prohíbe indicar dosis, posología, vía y duración. El de resumen prohíbe añadir
datos que no consten. El de prioridad acota el dominio a los valores admitidos.

## Validación de la respuesta

**Una respuesta que no cumple el formato es un error de integración, nunca un resultado.**
Devolver texto libre como si fuera una sugerencia estructurada sería peor que fallar.

| Caso | Resultado |
|---|---|
| Resumen sin texto utilizable | `502 gemini_response_error` |
| Sugerencia que no es JSON válido | `502 gemini_response_error` |
| JSON sin las listas esperadas | `502 gemini_response_error` |
| Prioridad fuera del dominio | `502 gemini_response_error` |
| Fallo del SDK | `502 gemini_service_error` |
| Falta `GEMINI_API_KEY` | `503 gemini_not_configured` |

Además se normaliza sin inventar: se descartan elementos que no son texto, se acotan a 5
familias y 8 principios activos, el resumen se recorta a 4000 caracteres, y se tolera que el
modelo envuelva el JSON en un bloque de código.

## Aislamiento del SDK — C-08

No ha sido posible verificar contra la documentación oficial del SDK que
`client.interactions.create(...)` y el identificador `gemini-3.7-flash` sean su superficie real.
Se usa el patrón **exactamente** como lo indica la documentación normativa del proyecto,
confinado a `GeminiService._invoke()` y `_get_client()`.

**Si la firma resultara distinta, el ajuste se limita a esos dos métodos.** Ni los servicios de
aplicación, ni las vistas, ni los tests dependen de ella: los tests inyectan un doble del
cliente. Hay un test que recorre `apps/` y falla si el SDK se importa en cualquier otro archivo.

La extracción del texto de la respuesta es deliberadamente defensiva (`text`, `output_text`,
`content`, o la propia cadena) por el mismo motivo.

## Variables de entorno

| Variable | Default | Notas |
|---|---|---|
| `GEMINI_API_KEY` | *(vacío)* | Vacío ⇒ los endpoints devuelven `503`. Nunca en el repositorio |
| `GEMINI_MODEL` | `gemini-3.7-flash` | |
| `GEMINI_TIMEOUT` | `15` | segundos |

## Tests

`tests/test_gemini_service.py` (35, sin base) y `tests/test_ai_endpoints.py` (19, requiere
PostgreSQL). **Ninguna llamada real al SDK.** Cobertura del 100 % en los módulos de IA.
