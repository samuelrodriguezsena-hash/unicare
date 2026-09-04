# UniCare — IMPLEMENTATION_PLAN

**Estado:** FASES 0–3 completas. Las decisiones **DEC-01 … DEC-16** y las contradicciones
**C-01 … C-08** están resueltas en [`DECISIONS.md`](DECISIONS.md); las únicas que siguen
abiertas dependen de terceros (URL real de la API de fármacos, verificación del SDK de Gemini).

Las 14 entidades del DER están implementadas. El contrato se verifica de forma automática en
`tests/test_der_contract.py` contra el inventario de `tests/der_inventory.py`.
**FASE 18 completa:** [`DEPLOYMENT.md`](DEPLOYMENT.md) con los 14 puntos exigidos. El
procedimiento se **ensayo contra un PostgreSQL real** con settings de produccion: `check
--deploy`, `migrate` desde una base vacia (14 tablas del DER + usuario `system`),
`createsuperuser`, login JWT, liveness y readiness (incluido el 503 con Redis caido), y marcha
atras de migraciones. El ensayo destapo que el job `configuracion-de-produccion` del pipeline
**habria fallado en su primera ejecucion**: la clave de ejemplo tenia 35 caracteres y
`check --deploy --fail-level WARNING` emite W009 por debajo de 50. Corregido y cubierto por un
test que lee el entorno del propio workflow.

**FASE 17 completa:** imagen de produccion endurecida y `docker-compose.prod.yml` (imagen
inmutable, sin puertos al exterior salvo `web` en loopback, logs acotados, PostgreSQL externo).
La sonda de salud pasa a ser `scripts/healthcheck.py`. Se detectaron y corrigieron **dos fallos
que dejaban el contenedor *unhealthy* para siempre** (DEC-40, DEC-41), ejecutando la aplicacion
WSGI con settings de produccion. 40 tests nuevos en `tests/test_docker.py`. Ver
[`DOCKER.md`](DOCKER.md). El build de la imagen **no se ejecuta en local** (no hay engine de
Docker en este entorno) pero **si en CI**, donde paso el 2026-09-04.

**FASE 16 completa:** pipeline de GitHub Actions con tres jobs (calidad, settings de
producción, imagen) y `scripts/ci.sh` para ejecutar los mismos pasos en local. Ver
[`CI.md`](CI.md). **Ejecutado en GitHub Actions el 2026-09-04 sobre el commit `30bb668`: los
tres jobs pasaron**, incluido el que construye la imagen y comprueba que el contenedor se
declara sano.

**FASE 15 completa:** 912 tests y **100 % de cobertura** (gate del 85 %), aislamiento de red
verificado, factories de `factory-boy` y garantías sobre la propia suite. Ver
[`TESTING.md`](TESTING.md).

**FASE 14 completa:** Sentry con saneado agresivo de datos clínicos, integraciones de Django,
Celery y logging, y trazabilidad repartida entre Sentry y `AUDIT_LOG`. Ver
[`OBSERVABILIDAD.md`](OBSERVABILIDAD.md).

**FASE 13 completa:** endpoints JWT, verificación real de la compatibilidad de `core.User` con
simplejwt (C-02) y garantía de que ningún endpoint queda desprotegido. Ver
[`AUTENTICACION.md`](AUTENTICACION.md).

**FASE 12 completa:** importación CSV/XLSX con validación por fila, transacción por fila,
procesamiento asíncrono y reporte. Ver [`CARGA_MASIVA.md`](CARGA_MASIVA.md).

**FASE 11 completa:** recordatorios a −48 h/−24 h sobre `APPOINTMENT_REMINDER`, cuatro tareas
Celery, `beat` estático activado y `NotificationService` con backend intercambiable. Ver
[`RECORDATORIOS.md`](RECORDATORIOS.md). Los reintentos viven en Celery, sin persistir el
contador (C-05).

**FASE 10 completa:** agenda con CRUD y cancelación, priorización con IA sobre las tres
columnas del DER, confirmación profesional y vista de calendario día/semana/mes. Ver
[`API_APPOINTMENTS.md`](API_APPOINTMENTS.md). La programación y el envío de recordatorios
quedan para la FASE 11.

**FASE 9 completa:** `GeminiService` con la superficie del SDK confinada a `_invoke()`,
prompts versionados y deterministas, validación estricta de la respuesta, y los endpoints de
resumen clínico y sugerencia de tratamiento. Ver [`IA.md`](IA.md). **C-08 sigue abierto**: el
patrón de invocación no es verificable, sólo está aislado.

**FASE 8 completa:** planes de tratamiento con alta atómica, asociación de medicamentos contra
la API externa con snapshots y validación cruzada, y alternativas por familia farmacológica.
Ver [`API_MEDICATIONS.md`](API_MEDICATIONS.md). La sugerencia de tratamiento con IA queda para
la FASE 9.

**FASE 6 completa:** CRUD de pacientes con baja lógica, búsqueda y filtros (nombre,
identificación, edad, patología principal, estado), historial clínico con entradas y notas, y
catálogo de patologías. Ver [`API_PEOPLE.md`](API_PEOPLE.md). El resumen clínico con Gemini
(`ai-summary`) queda para la FASE 9.

**FASE 5 completa:** auditoría (signals + middleware + `AuditService`), usuario técnico `system`,
validadores reutilizables, política de permisos y API de consulta/exportación de auditoría.
Ver [`AUDITORIA.md`](AUDITORIA.md).

**FASE 4 completa.** Las cinco migraciones iniciales están generadas, verificadas de forma
estática (`tests/test_migrations.py`) y **aplicadas contra PostgreSQL 16.4 real**. El esquema
físico resultante se compara con el DER en `tests/test_schema_postgresql.py`, que además
ejercita las restricciones contra la base. Ese módulo se salta solo cuando no hay PostgreSQL
accesible, de modo que la suite sigue siendo ejecutable sin infraestructura.

La **FASE 7** (cliente de la API de fármacos) se adelantó y está completa en su versión de
consulta en tiempo real: `GET /api/v1/farmacos/`, documentada en [`API_FARMACOS.md`](API_FARMACOS.md).
Sin caché Redis, sin Celery y sin persistencia, por decisión explícita de alcance.

---

## 1. Inventario del DER

Ver [`DER_ANALYSIS.md`](DER_ANALYSIS.md) §§ 1–8 (entidades, campos, PK, FK, restricciones,
nulabilidad, cardinalidades, enums). No se reproduce aquí para evitar dos fuentes de verdad.

Resumen: **14 tablas**, **139 columnas físicas**, **34 FK** (12 de dominio + 22 de auditoría),
**6 restricciones UNIQUE** declaradas + 1 regla textual, **9 columnas enum sin dominio de
valores definido**.

---

## 2. Mapeo DER → modelo Django

Reglas transversales aplicadas a las 14 tablas:

- `class Meta: db_table = "<NOMBRE_EXACTO_DEL_DER>"` en minúsculas
  (p. ej. `clinical_history_entry`). **Confirmar mayúsculas/minúsculas — ver DEC-09 abajo.**
- PK explícita: `BigAutoField(primary_key=True, db_column="<pk_del_der>")`.
  No se usa el `id` implícito de Django en ninguna tabla.
- FK: nombre de atributo Python sin sufijo `_id` (p. ej. `patient`), con
  `db_column="patient_id"` para preservar el nombre físico del DER.
- `null=True` exactamente donde el DER lo permite (§6 del análisis); `null=False` en el resto.
- `blank` se ajusta a la validación de formularios/DRF y **no** afecta al esquema físico.
- **No** se usa `managed = False` en ninguna tabla.
- **No** se usa `ManyToManyField` en ninguna relación.
- **No** se sustituye ninguna tabla por `JSONField`. `AUDIT_LOG.old_values`/`new_values` usan
  `JSONField` porque el DER declara `jsonb`.

| Tabla DER | Modelo Django | `db_table` | Hereda `Auditor` | Observaciones |
|---|---|---|---|---|
| `USER` | `User` | `user` | No | `AUTH_USER_MODEL`. Bloqueado por **DEC-06** |
| `PATIENT` | `Patient` | `patient` | Sí | `is_active` para baja lógica |
| `CLINICAL_HISTORY` | `ClinicalHistory` | `clinical_history` | Sí | `OneToOneField` a `Patient` (el DER declara UNIQUE) |
| `CLINICAL_HISTORY_ENTRY` | `ClinicalHistoryEntry` | `clinical_history_entry` | Sí | |
| `NOTE` | `Note` | `note` | Sí | |
| `PATHOLOGY` | `Pathology` | `pathology` | Sí | |
| `PATIENT_PATHOLOGY` | `PatientPathology` | `patient_pathology` | Sí | 2 constraints UNIQUE (compuesta + parcial `is_primary`) |
| `TREATMENT_PLAN` | `TreatmentPlan` | `treatment_plan` | Sí | `pathology` FK nullable |
| `TREATMENT_PLAN_MEDICATION` | `TreatmentPlanMedication` | `treatment_plan_medication` | Sí | Sin FK a catálogo local |
| `APPOINTMENT` | `Appointment` | `appointment` | Sí | |
| `APPOINTMENT_REMINDER` | `AppointmentReminder` | `appointment_reminder` | **No** | El DER no le da campos de auditoría (D-02) |
| `AUDIT_LOG` | `AuditLog` | `audit_log` | **No** | Sólo `created_at`; sin `updated_*` ni `*_by` |
| `IMPORT_BATCH` | `ImportBatch` | `import_batch` | Sí | |
| `IMPORT_BATCH_ROW` | `ImportBatchRow` | `import_batch_row` | Sí | |

### 2.1 Modelo abstracto `Auditor` (`apps/core/models.py`)

```
created_at  DateTimeField(auto_now_add=True)           NOT NULL
updated_at  DateTimeField(auto_now=True)               NOT NULL
created_by  FK(USER, null=True, db_column="created_by", on_delete=SET_NULL, related_name="+")
updated_by  FK(USER, null=True, db_column="updated_by", on_delete=SET_NULL, related_name="+")
class Meta: abstract = True
```

Se aplica **únicamente** a las 11 tablas que el DER dota de los cuatro campos.
`APPOINTMENT_REMINDER`, `AUDIT_LOG` y `USER` **no** lo heredan.

### 2.2 Enums

Se implementan como `models.TextChoices` con `db_column` sobre `CharField`, **no** como tipos
`ENUM` nativos de PostgreSQL — Django no gestiona tipos enum nativos de forma reproducible y su
alteración rompería la reproducibilidad de migraciones exigida por el proyecto. El contrato
lógico (dominio cerrado de valores) se conserva mediante `choices` + `CheckConstraint`.
**Esto es una interpretación de "enum(...)" y requiere aprobación — DEC-10.**

Los **valores** de cada enum siguen bloqueados por **DEC-03**.

---

## 3. Mapeo entidad → app

| App | Modelos | Justificación |
|---|---|---|
| `core` | `User`, `AuditLog`, `Auditor` (abstracto) | Identidad y auditoría son transversales. `USER` es FK de las 11 tablas auditadas y de `AUDIT_LOG`; ubicarlo en `core` evita dependencias circulares entre apps de dominio. |
| `people` | `Patient`, `ClinicalHistory`, `ClinicalHistoryEntry`, `Note`, `Pathology`, `PatientPathology` | La documentación asigna a `people` "pacientes, historial clínico, patologías". `Note` se incorpora por su FK a `ClinicalHistory` (D-05). |
| `medications` | `TreatmentPlan`, `TreatmentPlanMedication` | La documentación asigna a `medications` "planes de tratamiento, medicamentos asociados e integración con la API externa". |
| `appointments` | `Appointment`, `AppointmentReminder` | Directo de la documentación. |
| `massive_load` | `ImportBatch`, `ImportBatchRow` | Directo de la documentación. |

**Dependencias entre apps (sin ciclos):**
`core` ← `people` ← `medications`; `core` ← `people` ← `appointments`;
`core` ← `people` ← `massive_load`.

`medications.TreatmentPlan` referencia `people.Patient` y `people.Pathology`.
`appointments.Appointment` referencia `people.Patient`.
`massive_load` no tiene FK a `people` (D-04), sólo dependencia de servicio.

---

## 4. Endpoints previstos

Prefijo: `/api/v1/`. Todos paginados salvo indicación contraria. Autenticación JWT.
Los endpoints de escritura requieren usuario autenticado (C-03).

### 4.1 `core`

| Método | Ruta | Descripción |
|---|---|---|
| POST | `auth/token/` | Obtención de par access/refresh |
| POST | `auth/token/refresh/` | Refresco |
| POST | `auth/token/verify/` | Verificación |
| GET | `audit-logs/` | Consulta de auditoría; filtros `entity_type`, `entity_id`, `user`, `action`, rango de fechas |
| GET | `audit-logs/{id}/` | Detalle, incluye diff derivado `old_values`/`new_values` (D-03) |
| GET | `audit-logs/export/` | Exportación CSV |
| GET | `health/` | Liveness — no toca dependencias externas |
| GET | `health/ready/` | Readiness — verifica PostgreSQL y Redis; **no** verifica Gemini ni la API de fármacos |

### 4.2 `people`

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `patients/` | Listado con búsqueda y filtros / creación |
| GET / PATCH | `patients/{id}/` | Detalle / actualización parcial |
| POST | `patients/{id}/deactivate/` | Baja lógica (`is_active=False`). **No existe DELETE** |
| GET | `patients/{id}/clinical-history/` | Historial 1:1 con entradas y notas |
| GET / POST | `patients/{id}/pathologies/` | `PATIENT_PATHOLOGY` del paciente |
| PATCH / DELETE | `patient-pathologies/{id}/` | Actualización / desasociación |
| GET / POST | `clinical-histories/{id}/entries/` | `CLINICAL_HISTORY_ENTRY` |
| GET / POST | `clinical-histories/{id}/notes/` | `NOTE` |
| POST | `patients/{id}/ai-summary/` | Resumen clínico Gemini; persiste en `last_ai_summary` + `last_ai_summary_at` |
| GET / POST | `pathologies/` | Catálogo de patologías |
| GET / PATCH | `pathologies/{id}/` | Detalle / actualización. **Sin DELETE** (A-09) |

Filtros de `patients/`: `search` (nombre/apellido), `identification_number`,
`age_min` / `age_max` (derivados de `date_of_birth` en SQL, sin columna nueva),
`primary_pathology` (vía `PATIENT_PATHOLOGY.is_primary`), `is_active`.

### 4.3 `medications`

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `treatment-plans/` | Listado / creación (atómica con medicamentos) |
| GET / PATCH | `treatment-plans/{id}/` | Detalle / actualización |
| GET / POST | `treatment-plans/{id}/medications/` | Asociar medicamento; ejecuta validación cruzada |
| PATCH / DELETE | `treatment-plan-medications/{id}/` | Actualizar / quitar |
| GET | `treatment-plan-medications/{id}/alternatives/` | Alternativas por `Familia_Farmaco` vía API externa |
| GET | `pharma/search/` | Proxy de autocompletado a `GET /v1/farmacos` (filtros exactos, case-sensitive) |
| POST | `treatment-suggestions/` | Sugerencia IA a partir de una patología. **No persiste** (C-06 / DEC-07) |

### 4.4 `appointments`

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `appointments/` | Listado / creación; dispara priorización IA |
| GET / PATCH | `appointments/{id}/` | Detalle / reprogramación |
| POST | `appointments/{id}/cancel/` | Cancelación (cambia `status`) |
| POST | `appointments/{id}/priority/` | Confirmación profesional → `priority_final` |
| GET | `appointments/calendar/` | Eventos para calendario; parámetros `view=day|week|month`, `date` |
| GET | `appointments/{id}/reminders/` | Recordatorios asociados |

`appointments/calendar/` es una **representación alternativa** del mismo modelo; no se añade
ninguna columna ni tabla para soportarla.

### 4.5 `massive_load`

| Método | Ruta | Descripción |
|---|---|---|
| POST | `import-batches/` | Subida CSV/XLSX; encola tarea Celery |
| GET | `import-batches/` | Listado de lotes |
| GET | `import-batches/{id}/` | Estado y contadores |
| GET | `import-batches/{id}/rows/` | Filas con `status` y `error_message`; filtro por estado |
| GET | `import-batches/{id}/report/` | Reporte descargable (CSV) |

---

## 5. Servicios (capa de aplicación)

`apps/<app>/services/`. Los ViewSets son delgados; los serializers sólo validan y representan.

| Servicio | App | Responsabilidad |
|---|---|---|
| `AuditService` | `core` | Construye y persiste `AUDIT_LOG`. Resuelve el usuario responsable (C-04) |
| `PatientService` | `people` | Alta, baja lógica, creación del `CLINICAL_HISTORY` 1:1 |
| `ClinicalHistoryService` | `people` | Entradas, notas, ensamblado del historial estructurado para IA |
| `ClinicalSummaryService` | `people` | Orquesta `GeminiService.generate_clinical_summary()` y persiste el resumen |
| `PathologyService` | `people` | Asociación paciente–patología, regla `is_primary` |
| `TreatmentService` | `medications` | Planes, asociación de medicamentos, validación cruzada, alternativas |
| `TreatmentSuggestionService` | `medications` | Sugerencia IA por patología; marca y advertencia obligatorias |
| `AppointmentService` | `appointments` | CRUD, reprogramación, cancelación, programación de recordatorios |
| `AppointmentPriorityService` | `appointments` | Orquesta `GeminiService.prioritize_appointment()` |
| `CalendarService` | `appointments` | Serialización de citas a eventos de calendario |
| `NotificationService` | `core` | Interfaz abstracta de envío. Implementación inicial: `LoggingNotificationBackend`. Email/SMS se añaden como backends sin tocar el dominio |
| `ImportService` | `massive_load` | Parseo, validación por fila, upsert de paciente, asociación de patología, contadores |
| `ImportReportService` | `massive_load` | Generación del reporte |

**Prohibiciones aplicadas:** ninguna llamada `httpx` ni Gemini en `models.py`, `serializers.py`
ni `views.py`. Toda integración pasa por `Service → Client → API externa`.

---

## 6. Integraciones externas

### 6.1 `PharmaceuticalAPIClient` (`apps/core/clients/` o `apps/medications/clients/`)

- Transporte `httpx.Client` reutilizable (connection pooling), timeout configurable
  (`FARMACOS_API_TIMEOUT`, default 5 s), base URL desde `FARMACOS_API_BASE_URL`.
- Filtros soportados, **exactos y case-sensitive** tal como documenta la API:
  `Nombre_Medicamento`, `Dosis_Comun`, `Compuesto_Principal`, `Patologia_Comun`,
  `Familia_Farmaco`.
- Semántica de respuesta, aplicada literalmente:
  - `200` + array (posiblemente `[]`) → resultado válido. **`[]` no es error.**
  - `404` → error del recurso. **No se interpreta como "sin resultados".**
  - `400` / `500` → error traducido a excepción de dominio.
- Caché Redis por combinación de filtros, con TTL configurable
  (`FARMACOS_CACHE_TTL`) e invalidación explícita. La caché **no** es fuente de verdad
  ni constituye un catálogo local.
- **Bloqueado por C-07** (URL placeholder): sólo se ejercitará con mocks.

### 6.2 `GeminiService` (`apps/core/services/gemini.py`)

- SDK oficial `from google import genai`; `client = genai.Client()` con `GEMINI_API_KEY`
  desde el entorno.
- Toda invocación al SDK confinada a un único método privado `_invoke(prompt: str) -> str`,
  con el patrón documentado
  `client.interactions.create(model=settings.GEMINI_MODEL, input=...)`.
  Modelo configurable, default `gemini-3.7-flash`. **Ver C-08.**
- Métodos públicos: `generate_clinical_summary()`, `suggest_treatment()`,
  `prioritize_appointment()`.
- Prompts estructurados, deterministas, versionados en `apps/core/prompts/`.
- **Validación obligatoria de la respuesta** antes de devolverla al cliente: forma esperada,
  longitud, y para la priorización, pertenencia al dominio de valores permitido.
- Toda salida se etiqueta `"SUGERENCIA GENERADA POR IA"` e incluye la advertencia literal
  exigida por la documentación.

---

## 7. Tareas Celery

| Tarea | Tipo | Descripción |
|---|---|---|
| `appointments.schedule_reminders_for_appointment` | on-demand | Crea las filas `APPOINTMENT_REMINDER` a −48 h y −24 h al confirmarse la cita |
| `appointments.dispatch_due_reminders` | beat, periódica | Selecciona recordatorios vencidos y los envía vía `NotificationService`; actualiza `status`, `sent_at`, `failure_reason` |
| `massive_load.process_import_batch` | on-demand | Procesa el archivo fila a fila |
| `people.generate_clinical_summary_async` | on-demand (opcional) | Resumen Gemini fuera del ciclo request si la latencia lo exige |

Reintentos: `autoretry_for` + `max_retries` + backoff exponencial en `dispatch_due_reminders`
y en las tareas de integración. El contador **no** se persiste (C-05).

Broker y backend de resultados: Redis. `django-celery-beat` **no** se introduce salvo
autorización, ya que crea tablas propias fuera del DER; se usará el `beat_schedule`
estático de Celery.

---

## 8. Estrategia de testing

Objetivo: **≥ 85 % de cobertura**, con `--fail-under=85` como gate de CI.

| Nivel | Alcance |
|---|---|
| Modelos | PK/FK correctas, nulabilidad conforme al DER, las 6 UNIQUE + la parcial de `is_primary`, `Auditor` puebla `created_by`/`updated_by` |
| Esquema | Test que compara el esquema generado (`information_schema`) contra el inventario del DER: nombres de tabla, nombres de columna, nulabilidad y restricciones únicas |
| API | CRUD de pacientes, búsqueda, filtros por edad y patología principal, historial, planes, citas, recordatorios, importaciones; códigos 400/401/403/404/409 |
| Integraciones | `respx` para mockear `httpx` (incl. `200 + []`, `404`, `400`, `500`, timeout); `unittest.mock` para el SDK de Gemini. **Cero llamadas reales** |
| Celery | `CELERY_TASK_ALWAYS_EAGER` para el flujo; tests explícitos de scheduling, fallo y reintento |
| Massive load | CSV válido, CSV inválido, XLSX, paciente existente, paciente nuevo, patología duplicada, error por fila que no aborta el lote, reporte |
| Auditoría | Cada operación crítica genera exactamente un `AUDIT_LOG` con `old_values`/`new_values` correctos |
| Seguridad | Endpoints de escritura rechazan peticiones no autenticadas |
| N+1 | `assertNumQueries` en los listados de pacientes, planes y citas |

Herramientas: `pytest`, `pytest-django`, `factory-boy`, `coverage`, `respx`.
Base de datos de test: PostgreSQL (no SQLite — el esquema usa `jsonb` y constraints parciales).

---

## 9. Variables de entorno

Todas irán a `.env.example` **sin valores reales**. `.env` estará en `.gitignore`.

| Variable | Default | Notas |
|---|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.development` | |
| `DJANGO_SECRET_KEY` | — | Obligatoria, sin default en producción |
| `DJANGO_DEBUG` | `False` | |
| `DJANGO_ALLOWED_HOSTS` | — | Lista separada por comas |
| `DATABASE_URL` | — | PostgreSQL. Nunca SQLite en producción |
| `REDIS_URL` | — | Caché |
| `CELERY_BROKER_URL` | `$REDIS_URL` | |
| `CELERY_RESULT_BACKEND` | `$REDIS_URL` | |
| `GEMINI_API_KEY` | — | **Nunca en el repositorio** |
| `GEMINI_MODEL` | `gemini-3.7-flash` | |
| `GEMINI_TIMEOUT` | `15` | segundos |
| `FARMACOS_API_BASE_URL` | — | Bloqueada por C-07 |
| `FARMACOS_API_TIMEOUT` | `5` | segundos |
| `FARMACOS_CACHE_TTL` | `900` | segundos |
| `SENTRY_DSN` | vacío | Vacío desactiva Sentry |
| `SENTRY_ENVIRONMENT` | `development` | |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | |
| `JWT_ACCESS_TOKEN_LIFETIME` | `15` | minutos |
| `JWT_REFRESH_TOKEN_LIFETIME` | `1440` | minutos |
| `CORS_ALLOWED_ORIGINS` | vacío | |
| `REMINDER_OFFSETS_HOURS` | `48,24` | Configurable, según la documentación |

---

## 10. Estrategia de deployment

- **Dockerfile de producción** multi-stage, usuario no root, `gunicorn`, sin secretos.
- **docker-compose de desarrollo**: `web`, `db` (PostgreSQL), `redis`, `worker`, `beat`.
- **Agnóstico de proveedor**: sin SDK ni configuración específica de AWS/GCP/Azure/Render/
  Railway/Fly. Todo por variables de entorno; `DATABASE_URL` y `REDIS_URL` como únicos puntos
  de acoplamiento a infraestructura.
- **Health checks:** `/api/v1/health/` (liveness) y `/api/v1/health/ready/` (readiness:
  PostgreSQL + Redis). Ninguno depende de Gemini ni de la API de fármacos.
- **`docs/DEPLOYMENT.md`** cubrirá los 14 puntos exigidos: requisitos, variables, creación de
  PostgreSQL, Redis, build, despliegue, migraciones, superusuario, Sentry, dominio, SSL,
  health checks, rollback y troubleshooting.
- **CI** (GitHub Actions): instalación → `ruff` → `black --check` → `flake8` (si se mantiene) →
  `pytest` → `coverage report --fail-under=85` → build Docker. Falla en cualquiera de ellos.

---

## 11. Orden de ejecución propuesto

Se respeta el orden FASE 1 … FASE 18 de la documentación, con estas dependencias de bloqueo:

| Fase | Bloqueada por |
|---|---|
| FASE 3 (modelos) | **C-01** (`PATIENT_PATHOLOGY` vs `PATIENT_MEDICAL_RECORD`), **DEC-01**, **DEC-03**, **DEC-04**, **DEC-10** |
| FASE 4 (migraciones) | FASE 3 + **DEC-06** (`AUTH_USER_MODEL` debe fijarse antes de la primera migración; cambiarlo después obliga a recrear la base) |
| FASE 5 (auditoría) | **DEC-08** (usuario `system`) |
| FASE 7 / 8 (fármacos) | **C-07** (URL real) — implementable contra mocks, no verificable en real |
| FASE 9 (Gemini) | **C-08** (confirmación del patrón del SDK) |
| FASE 11 (recordatorios) | **C-05** (aceptación de reintentos no persistidos) |
| FASE 13 (JWT / permisos) | **DEC-06**, **C-03** |

**`AUTH_USER_MODEL` es la decisión más urgente:** debe estar resuelta *antes* de generar la
primera migración. Es la única decisión cuyo aplazamiento tiene coste de retrabajo real.

---

## 12. Contradicciones detectadas

Consolidadas en [`DER_ANALYSIS.md`](DER_ANALYSIS.md) §9 (**C-01 … C-08**), §10 (**A-01 … A-09**),
§11 (**D-00 … D-06**) y §12 (**DEC-01 … DEC-08**).

Decisiones adicionales que surgen del plan, no del DER:

| ID | Decisión | Recomendación |
|---|---|---|
| **DEC-09** | Mayúsculas/minúsculas de `db_table` (el DER usa MAYÚSCULAS; PostgreSQL sin comillas plega a minúsculas) | Usar minúsculas: `patient`, `clinical_history`, … Es el mismo identificador para PostgreSQL |
| **DEC-10** | Implementar `enum(...)` como `CharField` + `choices` + `CheckConstraint`, en lugar de tipos `ENUM` nativos de PostgreSQL | Aprobar `CharField` + `choices`: preserva el dominio cerrado y mantiene las migraciones reproducibles |
| **DEC-11** | `django-celery-beat` (crea tablas fuera del DER) frente a `beat_schedule` estático | `beat_schedule` estático: cero tablas añadidas |
