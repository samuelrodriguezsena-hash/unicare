# API de pacientes e información clínica

Gestión de pacientes, historial clínico y patologías. Todos los endpoints requieren JWT y
usuario activo.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `/api/v1/patients/` | Listado con búsqueda y filtros / alta |
| GET / PATCH | `/api/v1/patients/{id}/` | Detalle / modificación parcial |
| POST | `/api/v1/patients/{id}/deactivate/` | Baja lógica |
| GET | `/api/v1/patients/{id}/clinical-history/` | Historial completo |
| GET / POST | `/api/v1/patients/{id}/pathologies/` | Patologías del paciente |
| PATCH / DELETE | `/api/v1/patient-pathologies/{id}/` | Modificar / desasociar |
| GET / POST | `/api/v1/clinical-histories/{id}/entries/` | Entradas del historial |
| GET / POST | `/api/v1/clinical-histories/{id}/notes/` | Notas |
| GET / POST | `/api/v1/pathologies/` | Catálogo de patologías |
| GET / PATCH | `/api/v1/pathologies/{id}/` | Detalle / modificación |

**No existe `DELETE` de pacientes ni de patologías.** El DER define `is_active` en `PATIENT`
para dar de baja, y `PATHOLOGY` no tiene campo de estado y está referenciada desde planes de
tratamiento (A-09). Intentarlo devuelve `405`.

## Alta de pacientes

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"identification_number":"1098765432","first_name":"Ana","last_name":"Gomez","date_of_birth":"1980-05-14"}' \
  http://localhost:8000/api/v1/patients/
```

El alta **crea también el historial clínico** en la misma transacción: el DER modela
`CLINICAL_HISTORY` como 1:1 obligatorio con `PATIENT`, así que un paciente sin historial sería
un estado inválido según el contrato.

`identification_number` es **obligatorio en la API** aunque en el DER sea nullable (A-01): la
documentación funcional lo exige como dato mínimo. Se impone en la entrada, no endureciendo el
esquema. Su formato lo valida `IDENTIFICATION_NUMBER_PATTERN` (DEC-17).

`is_active` no es escribible: la baja tiene su propio endpoint, para que sea una operación
explícita y auditable.

## Búsqueda y filtros

| Parámetro | Efecto |
|---|---|
| `search` | Coincidencia parcial en nombre **o** apellido, sin distinguir mayúsculas |
| `identification_number` | Coincidencia exacta |
| `age_min` / `age_max` | Rango de edad |
| `primary_pathology` | ID de la patología marcada como principal |
| `is_active` | `true` / `false` |
| `ordering` | `last_name`, `first_name`, `created_at` (prefijo `-` para descendente) |

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/patients/?search=gomez&age_min=40&age_max=60"
```

La edad **no es una columna**: `age_min`/`age_max` se traducen a rangos sobre `date_of_birth`, y
el `age` de la respuesta se calcula al serializar. No se añadió nada al DER.

## Patologías del paciente

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"pathology_id": 3, "is_primary": true, "diagnosis_date": "2026-01-15"}' \
  http://localhost:8000/api/v1/patients/42/pathologies/
```

Dos reglas del DER se pueden violar aquí, y **las impone PostgreSQL**, no el código:

| Restricción | Situación | Respuesta |
|---|---|---|
| `uq_patient_pathology` | Misma patología dos veces en un paciente | `409` |
| `uq_patient_primary_pathology` | Segunda patología principal | `409` |

```json
{"detail": "El paciente ya tiene una patologia principal. Desmarca la actual antes de designar otra.", "code": "conflict"}
```

Desasociar (`DELETE`) sí es un borrado físico legítimo: `PATIENT_PATHOLOGY` no define campo de
estado, y la operación queda registrada en `AUDIT_LOG`.

## Historial clínico

`GET /api/v1/patients/{id}/clinical-history/` devuelve el historial con sus entradas, notas y
las patologías del paciente. Las entradas usan `CLINICAL_HISTORY_ENTRY` y las notas `NOTE`: **no
se crea ninguna estructura paralela de historial**.

`entry_type` admite `DIAGNOSIS`, `TREATMENT`, `OBSERVATION`, `PROCEDURE`, `FOLLOW_UP`
(DEC-03). Cualquier otro valor devuelve `400`.

Si un paciente no tuviera historial —posible en los creados por carga masiva— se crea al
consultarlo.

> `POST /api/v1/patients/{id}/ai-summary/` (resumen clínico con Gemini) llega en la **FASE 9**.

## Errores

| Situación | HTTP |
|---|---|
| Datos inválidos | `400` |
| Sin autenticar | `401` |
| Usuario inactivo | `403` |
| No existe | `404` |
| Método no permitido (p. ej. `DELETE` de paciente) | `405` |
| Identificación duplicada, patología repetida, segunda principal | `409` |

## Rendimiento

- El listado resuelve la patología principal con un `Prefetch` acotado a `is_primary`: evita el
  N+1 y además no trae todas las patologías de cada paciente para descartarlas.
  Verificado con `django_assert_max_num_queries`.
- El historial trae entradas, notas y patologías con `prefetch_related`.
- Los filtros de edad comparan contra `date_of_birth` con un índice utilizable, sin funciones
  sobre la columna.

## Tests

`tests/test_people_api.py` (56 tests, requiere PostgreSQL) y `tests/test_people_filters.py`
(cálculo de edades, sin base). Incluyen la comprobación de extremo a extremo de que una petición
HTTP real genera `AUDIT_LOG` con el usuario correcto y rellena `created_by`.
