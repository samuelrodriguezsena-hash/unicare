# API de agenda y citas

Gestión de citas, priorización asistida por IA y vista de calendario. Todos los endpoints
requieren JWT y usuario activo.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `/api/v1/appointments/` | Listado filtrable / agendar |
| GET / PATCH | `/api/v1/appointments/{id}/` | Detalle / reprogramar |
| POST | `/api/v1/appointments/{id}/cancel/` | Cancelar |
| POST | `/api/v1/appointments/{id}/priority/` | Confirmación profesional de la prioridad |
| GET | `/api/v1/appointments/{id}/reminders/` | Recordatorios de la cita |
| GET | `/api/v1/appointments/calendar/` | Eventos para calendario |

Filtros del listado: `patient`, `status`, `priority`, `scheduled_after`, `scheduled_before`,
`ordering`.

**No existe `DELETE`.** Una cita se cancela (`status = CANCELLED`), no se borra.

## Agendar

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"patient":42,"scheduled_at":"2026-09-15T10:00:00Z","reason":"Control post-quimioterapia"}' \
  http://localhost:8000/api/v1/appointments/
```

`status` admite `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, `NO_SHOW` (DEC-03). El DER
lo declara nullable, pero una cita recién agendada sin estado no es útil: se aplica
`SCHEDULED` por defecto **en la entrada de la API**, sin endurecer el esquema.

Cancelar es idempotente. El DER **no define ninguna máquina de estados** para `status`, así que
no se inventa una: no se prohíben transiciones que el contrato no prohíbe.

## Priorización con IA

Al agendar se solicita una prioridad sugerida. El DER define tres columnas, y DEC-02 fija su
semántica:

| Columna | Quién la escribe |
|---|---|
| `priority_suggested_by_ai` | **Sólo la IA** |
| `priority_final` | **Sólo un profesional**, vía `POST .../priority/` |
| `priority` | El enum operativo de la agenda |

`priority_final` vacío con `priority_suggested_by_ai` lleno = **la sugerencia sigue pendiente de
validación**. Es el flujo de aprobación de la documentación, materializado sobre columnas que ya
existen (C-06), sin crear ninguna tabla. La respuesta lo expone como
`ai_priority_pending_validation`, que es derivado y no una columna.

**Si la IA falla, la cita se agenda igual** (DEC-26): `priority_suggested_by_ai` queda vacío y
nada más. Es lo contrario de lo que ocurre al asociar un medicamento (DEC-21), donde el dato
externo forma parte de la integridad del registro. Aquí la sugerencia es orientativa, y bloquear
una cita clínica por una caída del proveedor de IA sería desproporcionado.

El cliente **no puede** enviar `priority_suggested_by_ai` ni `priority_final` al agendar: si
pudiera, haría pasar por validada una prioridad que nadie ha revisado.

### Confirmación profesional

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"priority_final":"ROUTINE_CONTROL"}' \
  http://localhost:8000/api/v1/appointments/7/priority/
```

Escribe `priority_final` y también `priority`, el enum con el que trabaja la agenda: DEC-02
impide que **la IA** escriba esos campos, no que lo haga un profesional de forma explícita.

**La sugerencia original se conserva.** Si el profesional discrepa, quedan registrados los dos
valores y la trazabilidad no se pierde.

## Calendario

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "http://localhost:8000/api/v1/appointments/calendar/?view=week&date=2026-09-15"
```

`view` admite `day`, `week` (empieza en lunes) y `month`; `date` por defecto es hoy. Se puede
filtrar por `patient`.

```json
{
  "view": "week",
  "start": "2026-09-14T00:00:00+00:00",
  "end": "2026-09-21T00:00:00+00:00",
  "events": [
    {
      "id": 7,
      "title": "Ana Gomez",
      "start": "2026-09-15T10:00:00+00:00",
      "extendedProps": {
        "patient": 42, "status": "SCHEDULED", "priority": null,
        "priority_final": null, "priority_suggested_by_ai": "URGENT",
        "reason": "Control post-quimioterapia"
      }
    }
  ]
}
```

Es una **representación alternativa del mismo modelo**: no se añadió ninguna columna ni tabla
para soportarla. Hay un test que lo verifica.

> **Limitación del DER:** `APPOINTMENT` define `scheduled_at` pero **no define duración ni hora
> de fin**. Por eso los eventos no llevan `end`: inventar una duración por defecto sería añadir
> información clínica que el contrato no contiene. Las librerías de calendario representan
> correctamente un evento con sólo `start`.

## Recordatorios

`GET /api/v1/appointments/{id}/reminders/` es de **sólo lectura**: los recordatorios los
programa el sistema, no el cliente. Su generación y envío (−48 h y −24 h) llegan en la
**FASE 11** con Celery. Hasta entonces la lista está vacía.

## Errores

| Situación | HTTP |
|---|---|
| Datos inválidos, estado o prioridad fuera del enum, vista de calendario desconocida | `400` |
| Sin autenticar / usuario inactivo | `401` / `403` |
| Cita inexistente | `404` |
| `DELETE` de una cita, `POST` a recordatorios | `405` |

## Rendimiento

- El listado usa `select_related("patient")` y `prefetch_related("reminders")`: 4 consultas
  independientemente del número de citas.
- El calendario resuelve en **una sola consulta**.
- Ambos verificados con `django_assert_max_num_queries`.
- El filtrado por rango aprovecha los índices `ix_appointment_scheduled_at` y
  `ix_appointment_patient_date` (DEC-05).

## Tests

`tests/test_appointments_api.py` (45) y `tests/test_appointment_priority.py` (14). El segundo
prueba el servicio de priorización **real** con un doble de `GeminiService`, porque el primero
lo sustituye entero para probar la agenda: así ninguna de las dos capas queda sin ejercitar.
Ninguna llamada real al SDK. Requieren PostgreSQL.
