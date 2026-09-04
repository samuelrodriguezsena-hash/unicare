# UniCare — Matriz de trazabilidad

**DER → Modelo Django → App → API → Tests**

Estado: FASE 0. Ninguna fila está implementada todavía. La columna "Bloqueo" indica qué
decisión pendiente impide iniciar la implementación de esa fila.

---

## 1. Matriz principal

| # | Tabla DER | Modelo Django | `db_table` | App | Endpoints previstos | Tests previstos | Bloqueo |
|---|---|---|---|---|---|---|---|
| 1 | `USER` | `User` | `user` | `core` | `POST auth/token/`, `auth/token/refresh/`, `auth/token/verify/` | `test_user_model.py` (UNIQUE username/email, `is_active`), `test_auth_jwt.py` (obtención, refresco, token inválido, usuario inactivo) | **DEC-06**, C-02 |
| 2 | `AUDIT_LOG` | `AuditLog` | `audit_log` | `core` | `GET audit-logs/`, `GET audit-logs/{id}/`, `GET audit-logs/export/` | `test_audit_model.py` (jsonb, FK `user` NOT NULL), `test_audit_signals.py` (una entrada por operación crítica), `test_audit_api.py` (filtros, export CSV, permisos) | **DEC-08**, C-04 |
| 3 | `PATIENT` | `Patient` | `patient` | `people` | `GET/POST patients/`, `GET/PATCH patients/{id}/`, `POST patients/{id}/deactivate/` | `test_patient_model.py` (UNIQUE nullable en `identification_number`, `is_active`, auditoría), `test_patient_api.py` (CRUD, búsqueda por nombre e identificación, filtro por edad y patología principal, baja lógica, ausencia de DELETE), `test_patient_queries.py` (`assertNumQueries`) | **DEC-01**, A-01 |
| 4 | `CLINICAL_HISTORY` | `ClinicalHistory` | `clinical_history` | `people` | `GET patients/{id}/clinical-history/`, `POST patients/{id}/ai-summary/` | `test_clinical_history_model.py` (1:1 forzado por UNIQUE `patient_id`), `test_clinical_summary_service.py` (Gemini mockeado, persistencia de `last_ai_summary` y `last_ai_summary_at`, validación de respuesta, etiqueta y advertencia de IA) | C-08 |
| 5 | `CLINICAL_HISTORY_ENTRY` | `ClinicalHistoryEntry` | `clinical_history_entry` | `people` | `GET/POST clinical-histories/{id}/entries/` | `test_clinical_history_entry_model.py` (FK, `entry_type` nullable, `entry_date` NOT NULL), `test_clinical_history_entry_api.py` | **DEC-03** (valores de `entry_type`) |
| 6 | `NOTE` | `Note` | `note` | `people` | `GET/POST clinical-histories/{id}/notes/` | `test_note_model.py`, `test_note_api.py` | — |
| 7 | `PATHOLOGY` | `Pathology` | `pathology` | `people` | `GET/POST pathologies/`, `GET/PATCH pathologies/{id}/` | `test_pathology_model.py` (UNIQUE `name`), `test_pathology_api.py` (sin endpoint DELETE) | — |
| 8 | `PATIENT_PATHOLOGY` | `PatientPathology` | `patient_pathology` | `people` | `GET/POST patients/{id}/pathologies/`, `PATCH/DELETE patient-pathologies/{id}/` | `test_patient_pathology_model.py` (UNIQUE compuesta; UNIQUE parcial "máx. 1 `is_primary` por paciente"; violación → 409), `test_patient_pathology_api.py` | **C-01**, A-04 |
| 9 | `TREATMENT_PLAN` | `TreatmentPlan` | `treatment_plan` | `medications` | `GET/POST treatment-plans/`, `GET/PATCH treatment-plans/{id}/` | `test_treatment_plan_model.py` (FK `pathology` nullable), `test_treatment_plan_api.py` (creación atómica con medicamentos, rollback ante fallo) | **DEC-03**, **DEC-04** |
| 10 | `TREATMENT_PLAN_MEDICATION` | `TreatmentPlanMedication` | `treatment_plan_medication` | `medications` | `GET/POST treatment-plans/{id}/medications/`, `PATCH/DELETE treatment-plan-medications/{id}/`, `GET treatment-plan-medications/{id}/alternatives/`, `GET pharma/search/`, `POST treatment-suggestions/` | `test_tpm_model.py` (sin FK a catálogo local; snapshots), `test_pharma_client.py` (`200+[]`, 404, 400, 500, timeout, filtros case-sensitive, caché), `test_alternatives.py` (búsqueda por `Familia_Farmaco`, exclusión del propio medicamento), `test_cross_validation.py` (discrepancia `Patologia_Comun` → advertencia, **no** bloqueo), `test_treatment_suggestion.py` (etiqueta "SUGERENCIA GENERADA POR IA" + advertencia obligatoria; no persiste) | **C-07**, **C-08**, **DEC-07** |
| 11 | `APPOINTMENT` | `Appointment` | `appointment` | `appointments` | `GET/POST appointments/`, `GET/PATCH appointments/{id}/`, `POST appointments/{id}/cancel/`, `POST appointments/{id}/priority/`, `GET appointments/calendar/` | `test_appointment_model.py`, `test_appointment_api.py` (CRUD, reprogramación, cancelación), `test_priority_service.py` (Gemini mockeado; escribe sólo `priority_suggested_by_ai`; validación de la respuesta), `test_calendar_api.py` (vistas día/semana/mes; el modelo no cambia) | **DEC-02**, **DEC-03**, C-08 |
| 12 | `APPOINTMENT_REMINDER` | `AppointmentReminder` | `appointment_reminder` | `appointments` | `GET appointments/{id}/reminders/` | `test_reminder_model.py` (**sin** campos de auditoría, conforme al DER), `test_reminder_scheduling.py` (offsets −48 h y −24 h), `test_reminder_dispatch.py` (envío, fallo con `failure_reason`, reintento Celery no persistido, `NotificationService` mockeado) | **C-05**, **DEC-03** |
| 13 | `IMPORT_BATCH` | `ImportBatch` | `import_batch` | `massive_load` | `POST import-batches/`, `GET import-batches/`, `GET import-batches/{id}/`, `GET import-batches/{id}/report/` | `test_import_batch_model.py`, `test_import_api.py` (subida CSV y XLSX, contadores, reporte) | **DEC-03** |
| 14 | `IMPORT_BATCH_ROW` | `ImportBatchRow` | `import_batch_row` | `massive_load` | `GET import-batches/{id}/rows/` | `test_import_row_model.py`, `test_import_service.py` (fila inválida no aborta el lote; paciente existente vs nuevo; patología duplicada no se reinserta; mensajes de error: "ID de paciente no encontrado", "Formato de fecha incorrecto"; transaccionalidad por fila) | **D-04**, **DEC-03** |

---

## 2. Cobertura de funcionalidades transversales

| Funcionalidad | Componente | App | Endpoint | Tests | Bloqueo |
|---|---|---|---|---|---|
| Modelo abstracto de auditoría | `Auditor` | `core` | — | `test_auditor_mixin.py` (se aplica a 11 tablas, **no** a `USER`, `AUDIT_LOG`, `APPOINTMENT_REMINDER`) | — |
| Registro de auditoría | `AuditService` + signals/middleware | `core` | — | `test_audit_signals.py` | **DEC-08** |
| Cliente de fármacos | `PharmaceuticalAPIClient` | `core`/`medications` | — | `test_pharma_client.py` (`respx`) | **C-07** |
| Servicio Gemini | `GeminiService` | `core` | — | `test_gemini_service.py` (SDK mockeado; validación de respuesta) | **C-08** |
| Notificaciones | `NotificationService` + backends | `core` | — | `test_notification_service.py` (backend intercambiable; el dominio no conoce el proveedor) | — |
| Health check | vistas de salud | `core` | `GET health/`, `GET health/ready/` | `test_health.py` (readiness falla si PostgreSQL cae; **no** depende de Gemini ni de fármacos) | — |
| Permisos | clases DRF propias | `core` | — | `test_permissions.py` (escritura anónima → 401/403 en pacientes, tratamientos y citas) | **C-03**, **DEC-06** |
| Manejo de errores | exception handler DRF | `core` | — | `test_error_handling.py` (400/401/403/404/409/422/500; sin stack traces; errores externos traducidos a errores de dominio) | — |
| Fidelidad del esquema al DER | test de introspección | `core` | — | `test_schema_matches_der.py` (compara `information_schema` contra el inventario de `DER_ANALYSIS.md`) | FASE 4 |
| Sentry | inicialización | `config` | — | `test_sentry_config.py` (DSN vacío → desactivado; DSN no hardcodeado) | — |

---

## 3. Resumen de bloqueos por decisión

| Decisión | Filas de la matriz bloqueadas |
|---|---|
| **C-01** — `PATIENT_PATHOLOGY` vs `PATIENT_MEDICAL_RECORD` | 8 (y, por dependencia, 3, 9, 10, 14) |
| **DEC-06 / C-02** — `AUTH_USER_MODEL` | 1, 2 y toda la capa de permisos. **Bloquea la primera migración** |
| **DEC-03** — valores de los enums | 5, 9, 11, 12, 13, 14 |
| **C-07** — URL de la API de fármacos | 10 (implementable con mocks; no verificable en real) |
| **C-08** — patrón del SDK de Gemini | 4, 10, 11 |
| **DEC-01 / A-01** — `varchar` sin longitud | 1, 3, 10 |
| **DEC-04** — `ON DELETE` | todas las filas con FK |
| **C-05** — reintentos no persistidos | 12 |
| **DEC-07 / C-06** — persistencia de sugerencias IA | 10 |
| **DEC-08 / C-04** — usuario técnico `system` | 2, 12, 14 |
