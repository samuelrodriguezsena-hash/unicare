# UniCare — DER_ANALYSIS

**Fuente inspeccionada:** `Diagrama en blanco (2).png` (3829 x 2260 px), raíz del repositorio.
**Fecha de inspección:** 2026-08-30
**Estado:** FASE 0 — análisis. No se ha escrito código ni migraciones.

> **D-00 (discrepancia documental).** La documentación normativa referencia el archivo
> `"Diagrama en blanco (2)-1024.jpg"`. En el repositorio existe únicamente
> `Diagrama en blanco (2).png`. Se asume que es el mismo artefacto. **Requiere confirmación.**

---

## 1. Inventario de entidades detectadas

El DER contiene **14 tablas**:

| # | Tabla | Presente en la lista de la documentación |
|---|-------|------------------------------------------|
| 1 | `CLINICAL_HISTORY_ENTRY` | Sí |
| 2 | `CLINICAL_HISTORY` | Sí |
| 3 | `NOTE` | Sí |
| 4 | `PATIENT` | Sí |
| 5 | `APPOINTMENT` | Sí |
| 6 | `PATIENT_PATHOLOGY` | **No — no figura en la lista de la documentación** |
| 7 | `PATHOLOGY` | Sí |
| 8 | `APPOINTMENT_REMINDER` | Sí |
| 9 | `TREATMENT_PLAN` | Sí |
| 10 | `TREATMENT_PLAN_MEDICATION` | Sí |
| 11 | `USER` | Sí |
| 12 | `AUDIT_LOG` | Sí |
| 13 | `IMPORT_BATCH` | Sí |
| 14 | `IMPORT_BATCH_ROW` | Sí |

**`PATIENT_MEDICAL_RECORD` aparece en la lista de la documentación pero NO existe en el DER.**
Ver contradicción **C-01**.

---

## 2. Inventario de columnas (transcripción literal del DER)

Las columnas se transcriben exactamente como aparecen. La columna "Marca" reproduce el
indicador PK/FK del margen izquierdo del diagrama; la columna "Tipo / Restricción" reproduce
el texto de la derecha.

### 2.1 `CLINICAL_HISTORY_ENTRY`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `clinical_history_entry_id` | `bigint NOT NULL` |
| FK | `clinical_history_id` | `bigint NOT NULL` |
|  | `entry_type` | `enum(entry_type)` |
|  | `entry_date` | `date NOT NULL` |
|  | `description` | `text NOT NULL` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

### 2.2 `CLINICAL_HISTORY`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `clinical_history_id` | `bigint NOT NULL` |
| FK | `patient_id` | `bigint UNIQUE NOT NULL` |
|  | `last_ai_summary` | `text` |
|  | `last_ai_summary_at` | `datetime` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

### 2.3 `NOTE`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `note_id` | `bigint NOT NULL` |
| FK | `clinical_history_id` | `bigint NOT NULL` |
|  | `text` | `text NOT NULL` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

### 2.4 `PATIENT`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `patient_id` | `bigint NOT NULL` |
|  | `identification_number` | `varchar UNIQUE` |
|  | `first_name` | `varchar(100) NOT NULL` |
|  | `last_name` | `varchar(100) NOT NULL` |
|  | `date_of_birth` | `date` |
|  | `phone` | `varchar(30)` |
|  | `email` | `varchar(255)` |
|  | `address` | `varchar(255)` |
|  | `is_active` | `boolean NOT NULL` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: `identification_number` **no** está marcado `NOT NULL` en el DER, pese a ser UNIQUE.
`varchar` aparece **sin longitud**. Ver **A-01** y **A-02**.

### 2.5 `APPOINTMENT`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `appointment_id` | `bigint NOT NULL` |
| FK | `patient_id` | `bigint NOT NULL` |
|  | `scheduled_at` | `datetime NOT NULL` |
|  | `status` | `enum(status)` |
|  | `reason` | `text` |
|  | `priority` | `enum(priority)` |
|  | `priority_suggested_by_ai` | `varchar(30)` |
|  | `priority_final` | `varchar(30)` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: coexisten `priority` (enum) y `priority_final` (varchar 30). Ver **A-03**.

### 2.6 `PATIENT_PATHOLOGY`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `patient_pathology_id` | `bigint NOT NULL` |
| FK | `patient_id` | `bigint NOT NULL` |
| FK | `pathology_id` | `bigint NOT NULL` |
|  | `is_primary` | `bool; max 1 primary/patient` |
|  | `diagnosis_date` | `date` |
|  | `notes` | `text` |
|  | `uq_patient_pathology` | `UNIQUE(patient_id, pathology_id)` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: `uq_patient_pathology` **no es una columna**, es la declaración de una restricción UNIQUE
compuesta dibujada como fila. `is_primary` incluye una regla de negocio embebida en el DER
("max 1 primary/patient") que requiere una restricción única parcial. Ver **A-04** y **D-01**.

### 2.7 `PATHOLOGY`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `pathology_id` | `bigint NOT NULL` |
|  | `name` | `varchar(255) UNIQUE NOT NULL` |
|  | `description` | `text` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

### 2.8 `APPOINTMENT_REMINDER`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `reminder_id` | `bigint NOT NULL` |
| FK | `appointment_id` | `bigint NOT NULL` |
|  | `channel` | `enum(channel)` |
|  | `scheduled_at` | `datetime NOT NULL` |
|  | `sent_at` | `datetime` |
|  | `status` | `enum(status)` |
|  | `failure_reason` | `text` |

Notas: **no tiene** `created_at`, `updated_at`, `created_by`, `updated_by`. Ver **D-02**.
Tampoco tiene contador de reintentos. Ver **C-05**.

### 2.9 `TREATMENT_PLAN`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `treatment_plan_id` | `bigint NOT NULL` |
| FK | `patient_id` | `bigint NOT NULL` |
| *(sin marca)* | `pathology_id` | `bigint FK` |
|  | `name` | `varchar(255) NOT NULL` |
|  | `start_date` | `date NOT NULL` |
|  | `end_date` | `date` |
|  | `status` | `enum(status)` |
|  | `clinical_note` | `text` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: `pathology_id` no lleva marca "FK" en el margen izquierdo pero su tipo declara `FK`.
Se interpreta como FK **nullable** a `PATHOLOGY`. Ver **A-05**.

### 2.10 `TREATMENT_PLAN_MEDICATION`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `treatment_plan_medication_id` | `bigint NOT NULL` |
| FK | `treatment_plan_id` | `bigint NOT NULL` |
|  | `external_medication_id` | `varchar(100) NOT NULL` |
|  | `medication_name_snapshot` | `varchar — external snapshot` |
|  | `medication_family_snapshot` | `varchar — external snapshot` |
|  | `dose` | `varchar(100)` |
|  | `frequency` | `varchar(100)` |
|  | `duration` | `varchar(100)` |
|  | `route` | `varchar(100)` |
|  | `instructions` | `text` |
|  | `validation_status` | `varchar(30)` |
|  | `warning_flag` | `boolean` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: los dos campos `_snapshot` declaran `varchar` **sin longitud**. Ver **A-02**.
Confirma la regla "no catálogo local": el medicamento se referencia por
`external_medication_id` (string proveniente de la API externa) más snapshots desnormalizados.

### 2.11 `USER`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `user_id` | `bigint NOT NULL` |
|  | `username` | `varchar UNIQUE` |
|  | `email` | `varchar UNIQUE` |
|  | `is_active` | `boolean NOT NULL` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |

Notas: **no existe** `password`, ni `last_login`, ni `is_staff`, ni `is_superuser`, ni `role`.
Ver contradicciones **C-02** (JWT / Django auth) y **C-03** (permisos por rol).

### 2.12 `AUDIT_LOG`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `audit_id` | `bigint NOT NULL` |
| FK | `user_id` | `bigint NOT NULL` |
|  | `entity_type` | `varchar(100) NOT NULL` |
|  | `entity_id` | `bigint NOT NULL` |
|  | `action` | `enum(action)` |
|  | `old_values` | `jsonb` |
|  | `new_values` | `jsonb` |
|  | `created_at` | `datetime NOT NULL` |

Notas: `user_id` es `NOT NULL` — ver **C-04**. No existe columna `changes` — ver **D-03**.

### 2.13 `IMPORT_BATCH`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `import_batch_id` | `bigint NOT NULL` |
|  | `source_file_name` | `varchar(255) NOT NULL` |
|  | `source_file_type` | `varchar(50)` |
|  | `processed_at` | `datetime` |
|  | `total_rows` | `int` |
|  | `success_count` | `int` |
|  | `failure_count` | `int` |
|  | `status` | `enum(status)` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

### 2.14 `IMPORT_BATCH_ROW`

| Marca | Columna | Tipo / Restricción |
|-------|---------|--------------------|
| PK | `import_batch_row_id` | `bigint NOT NULL` |
| FK | `import_batch_id` | `bigint NOT NULL` |
|  | `row_number` | `int NOT NULL` |
|  | `identification_number` | `varchar(50)` |
|  | `patient_name_snapshot` | `varchar(255)` |
|  | `pathology_name_snapshot` | `varchar(255)` |
|  | `status` | `enum(status)` |
|  | `error_message` | `text` |
|  | `created_at` | `datetime NOT NULL` |
|  | `updated_at` | `datetime NOT NULL` |
| FK | `created_by` | `bigint FK` |
| FK | `updated_by` | `bigint FK` |

Notas: **no existe FK a `PATIENT`** ni a `PATIENT_PATHOLOGY`. La trazabilidad fila → paciente
creado es únicamente por `identification_number`. Ver **D-04**.

---

## 3. Claves primarias

Todas las tablas usan PK **surrogate, simple, `bigint NOT NULL`**, con nombre
`<tabla_en_singular>_id`. No hay PK compuestas. No hay UUID.

| Tabla | PK |
|---|---|
| `CLINICAL_HISTORY_ENTRY` | `clinical_history_entry_id` |
| `CLINICAL_HISTORY` | `clinical_history_id` |
| `NOTE` | `note_id` |
| `PATIENT` | `patient_id` |
| `APPOINTMENT` | `appointment_id` |
| `PATIENT_PATHOLOGY` | `patient_pathology_id` |
| `PATHOLOGY` | `pathology_id` |
| `APPOINTMENT_REMINDER` | `reminder_id` |
| `TREATMENT_PLAN` | `treatment_plan_id` |
| `TREATMENT_PLAN_MEDICATION` | `treatment_plan_medication_id` |
| `USER` | `user_id` |
| `AUDIT_LOG` | `audit_id` |
| `IMPORT_BATCH` | `import_batch_id` |
| `IMPORT_BATCH_ROW` | `import_batch_row_id` |

---

## 4. Claves foráneas

### 4.1 FK de dominio (dibujadas con conector en el DER)

| Origen | Columna | Destino | Nulabilidad |
|---|---|---|---|
| `CLINICAL_HISTORY` | `patient_id` | `PATIENT.patient_id` | NOT NULL + UNIQUE |
| `CLINICAL_HISTORY_ENTRY` | `clinical_history_id` | `CLINICAL_HISTORY.clinical_history_id` | NOT NULL |
| `NOTE` | `clinical_history_id` | `CLINICAL_HISTORY.clinical_history_id` | NOT NULL |
| `APPOINTMENT` | `patient_id` | `PATIENT.patient_id` | NOT NULL |
| `APPOINTMENT_REMINDER` | `appointment_id` | `APPOINTMENT.appointment_id` | NOT NULL |
| `PATIENT_PATHOLOGY` | `patient_id` | `PATIENT.patient_id` | NOT NULL |
| `PATIENT_PATHOLOGY` | `pathology_id` | `PATHOLOGY.pathology_id` | NOT NULL |
| `TREATMENT_PLAN` | `patient_id` | `PATIENT.patient_id` | NOT NULL |
| `TREATMENT_PLAN` | `pathology_id` | `PATHOLOGY.pathology_id` | NULL (ver A-05) |
| `TREATMENT_PLAN_MEDICATION` | `treatment_plan_id` | `TREATMENT_PLAN.treatment_plan_id` | NOT NULL |
| `IMPORT_BATCH_ROW` | `import_batch_id` | `IMPORT_BATCH.import_batch_id` | NOT NULL |
| `AUDIT_LOG` | `user_id` | `USER.user_id` | NOT NULL |

### 4.2 FK de auditoría (`created_by` / `updated_by` → `USER.user_id`)

Presentes, ambas nullable (`bigint FK`, sin `NOT NULL`), en:

`CLINICAL_HISTORY_ENTRY`, `CLINICAL_HISTORY`, `NOTE`, `PATIENT`, `APPOINTMENT`,
`PATIENT_PATHOLOGY`, `PATHOLOGY`, `TREATMENT_PLAN`, `TREATMENT_PLAN_MEDICATION`,
`IMPORT_BATCH`, `IMPORT_BATCH_ROW`.

**Ausentes en:** `USER`, `AUDIT_LOG`, `APPOINTMENT_REMINDER`.

Total: **22 FK de auditoría** (11 tablas × 2).

---

## 5. Restricciones UNIQUE

| Tabla | Restricción |
|---|---|
| `PATIENT` | `identification_number` UNIQUE (columna simple) |
| `CLINICAL_HISTORY` | `patient_id` UNIQUE (fuerza el 1:1 con `PATIENT`) |
| `PATHOLOGY` | `name` UNIQUE |
| `USER` | `username` UNIQUE |
| `USER` | `email` UNIQUE |
| `PATIENT_PATHOLOGY` | `uq_patient_pathology` = UNIQUE(`patient_id`, `pathology_id`) |
| `PATIENT_PATHOLOGY` | *(regla textual)* máximo 1 `is_primary` verdadero por paciente |

No hay ninguna otra restricción UNIQUE en el DER.

---

## 6. Nulabilidad — columnas que ADMITEN NULL

| Tabla | Columnas nullable |
|---|---|
| `CLINICAL_HISTORY_ENTRY` | `entry_type`, `created_by`, `updated_by` |
| `CLINICAL_HISTORY` | `last_ai_summary`, `last_ai_summary_at`, `created_by`, `updated_by` |
| `NOTE` | `created_by`, `updated_by` |
| `PATIENT` | `identification_number`, `date_of_birth`, `phone`, `email`, `address`, `created_by`, `updated_by` |
| `APPOINTMENT` | `status`, `reason`, `priority`, `priority_suggested_by_ai`, `priority_final`, `created_by`, `updated_by` |
| `PATIENT_PATHOLOGY` | `is_primary`, `diagnosis_date`, `notes`, `created_by`, `updated_by` |
| `PATHOLOGY` | `description`, `created_by`, `updated_by` |
| `APPOINTMENT_REMINDER` | `channel`, `sent_at`, `status`, `failure_reason` |
| `TREATMENT_PLAN` | `pathology_id`, `end_date`, `status`, `clinical_note`, `created_by`, `updated_by` |
| `TREATMENT_PLAN_MEDICATION` | `medication_name_snapshot`, `medication_family_snapshot`, `dose`, `frequency`, `duration`, `route`, `instructions`, `validation_status`, `warning_flag`, `created_by`, `updated_by` |
| `USER` | `username`, `email` |
| `AUDIT_LOG` | `action`, `old_values`, `new_values` |
| `IMPORT_BATCH` | `source_file_type`, `processed_at`, `total_rows`, `success_count`, `failure_count`, `status`, `created_by`, `updated_by` |
| `IMPORT_BATCH_ROW` | `identification_number`, `patient_name_snapshot`, `pathology_name_snapshot`, `status`, `error_message`, `created_by`, `updated_by` |

**Criterio aplicado:** se considera NOT NULL únicamente lo que el DER escribe explícitamente
como `NOT NULL`. Todo lo demás se implementará `null=True`. No se endurece la nulabilidad por
"buena práctica".

---

## 7. Relaciones y cardinalidades

Notación: `||` = exactamente uno; `o{` = cero o muchos (círculo + pata de gallo, tal como
aparece dibujado en el diagrama).

```
PATIENT           ||--|| CLINICAL_HISTORY          (1:1, forzado por UNIQUE(patient_id))
CLINICAL_HISTORY  ||--o{ CLINICAL_HISTORY_ENTRY    (1:N)
CLINICAL_HISTORY  ||--o{ NOTE                      (1:N)
PATIENT           ||--o{ APPOINTMENT               (1:N)
APPOINTMENT       ||--o{ APPOINTMENT_REMINDER      (1:N)
PATIENT           ||--o{ PATIENT_PATHOLOGY         (1:N)
PATHOLOGY         ||--o{ PATIENT_PATHOLOGY         (1:N)
PATIENT           ||--o{ TREATMENT_PLAN            (1:N)
PATHOLOGY         ||--o{ TREATMENT_PLAN            (1:N, opcional)
TREATMENT_PLAN    ||--o{ TREATMENT_PLAN_MEDICATION (1:N)
IMPORT_BATCH      ||--o{ IMPORT_BATCH_ROW          (1:N)
USER              ||--o{ AUDIT_LOG                 (1:N)
USER              ||--o{ <11 tablas>.created_by    (1:N, opcional)
USER              ||--o{ <11 tablas>.updated_by    (1:N, opcional)
```

`PATIENT_PATHOLOGY` es una **tabla asociativa explícita con atributos propios y auditoría**.
El DER la modela como entidad, **no** como M2M implícito. Por la regla del proyecto se
implementará como modelo Django explícito y **no** con `ManyToManyField`.

`TREATMENT_PLAN_MEDICATION` **no** apunta a ninguna tabla local de medicamentos: usa
`external_medication_id` (varchar) más snapshots. Consistente con "no crear catálogo local".

---

## 8. ENUM declarados sin dominio de valores

El DER declara nueve columnas enumeradas pero **no enumera sus valores**:

| Tabla | Columna | Tipo |
|---|---|---|
| `CLINICAL_HISTORY_ENTRY` | `entry_type` | `enum(entry_type)` |
| `APPOINTMENT` | `status` | `enum(status)` |
| `APPOINTMENT` | `priority` | `enum(priority)` |
| `APPOINTMENT_REMINDER` | `channel` | `enum(channel)` |
| `APPOINTMENT_REMINDER` | `status` | `enum(status)` |
| `TREATMENT_PLAN` | `status` | `enum(status)` |
| `AUDIT_LOG` | `action` | `enum(action)` |
| `IMPORT_BATCH` | `status` | `enum(status)` |
| `IMPORT_BATCH_ROW` | `status` | `enum(status)` |

Ver **DEC-03**: los valores concretos son una decisión pendiente y **no se inventarán**.

---

## 9. Contradicciones detectadas (bloqueantes)

### C-01 — `PATIENT_MEDICAL_RECORD` no existe en el DER

- **Documentación:** lista `PATIENT_MEDICAL_RECORD` entre las entidades del modelo.
- **DER:** no contiene esa tabla. Contiene `PATIENT_PATHOLOGY`, que la lista de la
  documentación no menciona.
- **Afecta:** app `people`, modelos, migraciones, carga masiva, filtro "por patología
  principal", flujo de sugerencia de tratamiento (que parte de "una patología del historial").
- **Alternativas:**
  1. La lista de la documentación está desactualizada; `PATIENT_PATHOLOGY` la sustituye.
  2. Son dos entidades distintas y falta `PATIENT_MEDICAL_RECORD` en el DER.
  3. Es un error de nombre y hay que renombrar una de las dos.
- **Recomendación:** opción 1. El DER es el contrato y la documentación declara explícitamente
  que su lista "NO sustituye la inspección del archivo visual". `PATIENT_PATHOLOGY` cubre
  funcionalmente todo lo que la documentación pide (patología principal, fecha de diagnóstico,
  notas, no duplicar patologías en carga masiva).
- **Decisión requerida:** confirmar que se implementa `PATIENT_PATHOLOGY` y se descarta
  `PATIENT_MEDICAL_RECORD`.

### C-02 — `USER` es incompatible con `django.contrib.auth` y con JWT

- **DER:** `USER` tiene `user_id`, `username`, `email`, `is_active`, `created_at`, `updated_at`.
- **Requerido por el stack:** `AbstractBaseUser` exige `password` y `last_login`;
  `PermissionsMixin` exige `is_superuser` más tablas M2M de grupos y permisos;
  `createsuperuser` y el admin exigen `is_staff`; `djangorestframework-simplejwt` exige un
  usuario con `password` verificable.
- **La documentación prohíbe explícitamente alterar `USER` sin autorización.**
- **Afecta:** FASE 13 completa (JWT y permisos), admin de Django, `createsuperuser`,
  toda la autenticación y, por dependencia, todos los endpoints protegidos.
- **Alternativas:**
  1. **Extender `USER`** con `password`, `last_login`, `is_staff`, `is_superuser` heredando de
     `AbstractBaseUser` + `PermissionsMixin`. Añade columnas y 2 tablas M2M
     (`user_groups`, `user_user_permissions`) no presentes en el DER.
  2. **`USER` como modelo puro del DER**, usando el `auth.User` estándar de Django en una tabla
     aparte con relación 1:1. Mantiene el DER intacto pero introduce una tabla adicional al
     esquema físico y duplica la identidad.
  3. **`AbstractBaseUser` sin `PermissionsMixin`**: añade sólo `password` y `last_login`
     (2 columnas), sin tablas M2M, con permisos resueltos por clases DRF propias.
     Impide usar el admin de Django tal cual.
- **Recomendación:** opción 3. Es el delta mínimo sobre el DER (2 columnas, 0 tablas nuevas),
  satisface JWT, y la documentación ya exige que "la lógica de permisos esté separada de la
  lógica de negocio", lo que encaja con permisos DRF propios en vez del framework de permisos
  de Django.
- **Decisión requerida:** elegir opción 1, 2 o 3. **Sin esta decisión no se puede implementar
  la FASE 13 ni ejecutar `migrate` con `AUTH_USER_MODEL` apuntando a `USER`.**

### C-03 — No existe soporte para roles / autorización diferenciada

- **Documentación:** exige permisos diferenciados sobre pacientes, tratamientos y citas, y que
  "los usuarios no autenticados no puedan ejecutar operaciones administrativas".
- **DER:** `USER` no tiene `role`, `is_staff`, ni relación a grupos.
- **Afecta:** app `core` (clases de permiso) y todos los ViewSets.
- **Alternativas:**
  1. Añadir `role` a `USER` (modifica el DER).
  2. Usar `Group`/`Permission` estándar de Django (añade tablas fuera del DER).
  3. Implementar sólo autenticación (`IsAuthenticated`) sin diferenciación por rol, dejando
     documentada la limitación.
- **Recomendación:** opción 3 para esta entrega, con las clases de permiso escritas de forma
  que aceptar roles después sea un cambio localizado. Se cumple el requisito literal
  ("no autenticados no ejecutan operaciones administrativas") sin tocar el DER.
- **Decisión requerida:** confirmar opción 3 o autorizar 1 / 2.

### C-04 — `AUDIT_LOG.user_id` es NOT NULL, pero hay operaciones sin usuario

- **DER:** `user_id bigint NOT NULL`.
- **Realidad del sistema:** las tareas Celery (envío de recordatorios, procesamiento masivo
  asíncrono) y cualquier comando de gestión se ejecutan sin request ni usuario autenticado.
- **Afecta:** `core` (auditoría), `appointments` (recordatorios), `massive_load`.
- **Alternativas:**
  1. No auditar operaciones sin usuario (pérdida de trazabilidad).
  2. Propagar siempre el usuario que originó la operación hasta la tarea Celery. Posible para
     la carga masiva; **imposible** para el `beat` de recordatorios.
  3. Crear un usuario técnico `system` en `USER` y usarlo como responsable de las operaciones
     automáticas. No modifica el esquema.
- **Recomendación:** opción 3 combinada con 2 — propagar el usuario real cuando exista y
  atribuir al usuario técnico `system` cuando el origen sea el planificador.
- **Decisión requerida:** autorizar la creación del usuario técnico `system` vía data migration.

### C-05 — Los recordatorios deben contemplar "reintento", pero el DER no lo persiste

- **Documentación:** "Debe contemplarse: reintento, errores, estado, trazabilidad — *cuando
  dichos campos estén presentes en el DER*".
- **DER (`APPOINTMENT_REMINDER`):** tiene `status`, `sent_at`, `failure_reason`. **No tiene**
  contador de reintentos.
- **Interpretación aplicada:** la propia documentación condiciona el requisito a la presencia
  del campo. Los reintentos se implementarán en la **capa Celery** (`autoretry_for`,
  `max_retries`, backoff), sin persistir el contador. `status` y `failure_reason` registran el
  resultado final.
- **Recomendación:** implementar así y no añadir columnas.
- **Decisión requerida:** confirmar que la ausencia de trazabilidad persistida del número de
  intentos es aceptable.

### C-06 — El flujo de aprobación de IA no tiene dónde persistirse por completo

- **Documentación:** exige un flujo `PENDIENTE DE VALIDACIÓN → APROBADA / RECHAZADA` para
  *toda* sugerencia clínica generada por Gemini y, a la vez, prohíbe crear tablas arbitrarias
  si el DER no contempla la estructura.
- **DER — soporte existente, parcial:**
  - Priorización de citas: `APPOINTMENT.priority_suggested_by_ai` (sugerencia) +
    `APPOINTMENT.priority_final` (decisión profesional) + `APPOINTMENT.priority`.
    **Suficiente** para el flujo, aunque sin estado explícito de "pendiente".
  - Medicación de un plan: `TREATMENT_PLAN_MEDICATION.validation_status` (varchar 30) +
    `warning_flag`. **Suficiente** para el flujo de validación cruzada.
  - Resumen clínico: `CLINICAL_HISTORY.last_ai_summary` + `last_ai_summary_at`.
    **No hay estado de aprobación**; es un campo de caché del último resumen.
  - **Sugerencia de tratamiento (`suggest_treatment`): no existe NINGUNA columna ni tabla donde
    persistirla, ni su estado, ni su aprobación.**
- **Afecta:** `medications` (sugerencia de tratamiento con IA), `people` (resumen clínico),
  frontend opcional ("flujo de aprobación de sugerencias IA").
- **Alternativas:**
  1. Devolver la sugerencia de tratamiento **sólo como respuesta de API, sin persistir**.
     Cumple el DER; el "flujo de aprobación" se materializa cuando el profesional decide crear
     un `TREATMENT_PLAN_MEDICATION` a partir de la sugerencia (con `validation_status`).
  2. Crear una tabla `AI_SUGGESTION` — **prohibido** sin autorización explícita.
- **Recomendación:** opción 1, documentando la limitación: no habrá historial persistido de
  sugerencias de tratamiento rechazadas.
- **Decisión requerida:** confirmar opción 1, o autorizar expresamente la tabla nueva.

### C-07 — La URL de la API de fármacos es un placeholder

- **Documentación:** `https://api.xxxxxx.com`, endpoint `GET /v1/farmacos`.
- **Problema:** el host no es un dominio real. No es posible verificar contrato, latencia ni
  comportamiento de errores.
- **Afecta:** FASE 7 y 8, y el objetivo no funcional de < 500 ms.
- **Recomendación:** implementar el cliente contra el contrato documentado (campos, filtros
  exactos y case-sensitive, `200 + []`, 400/404/500), configurado por `FARMACOS_API_BASE_URL`,
  y probarlo **exclusivamente con mocks**. No se ejecutará ninguna llamada real hasta recibir
  la URL definitiva.
- **Decisión requerida:** proporcionar la URL base real, o confirmar que sólo habrá mocks.

### C-08 — El patrón de invocación de Gemini indicado no es verificable

- **Documentación:** ordena usar `client.interactions.create(model="gemini-3.7-flash", input=...)`
  con `from google import genai`.
- **Problema:** no puedo verificar desde este entorno, contra la documentación oficial del SDK,
  que `client.interactions.create(...)` y el identificador `gemini-3.7-flash` sean la superficie
  correcta del paquete `google-genai`. **No voy a asumir otra firma ni inventarla.**
- **Recomendación:** implementar `GeminiService` de forma que **toda** invocación al SDK esté
  aislada en un único método privado (`_invoke`), con el patrón exactamente como está
  documentado y el modelo configurable vía `GEMINI_MODEL` (default `gemini-3.7-flash`). Si al
  ejecutar contra el SDK real la firma no existiera, el cambio queda confinado a ese método.
  Todos los tests mockean esa frontera.
- **Decisión requerida:** confirmar el patrón, o corregirlo antes de la FASE 9.

---

## 10. Ambigüedades detectadas (no bloqueantes, requieren criterio)

| ID | Ambigüedad | Interpretación propuesta |
|---|---|---|
| **A-01** | `PATIENT.identification_number` es UNIQUE pero **nullable**, mientras la documentación lo lista como dato mínimo obligatorio. | Respetar el DER: `null=True, unique=True`. PostgreSQL admite múltiples NULL en un índice único. La obligatoriedad se aplica **en el serializer de creación vía API**, no en el esquema. |
| **A-02** | `varchar` sin longitud en `PATIENT.identification_number`, `USER.username`, `USER.email`, `TREATMENT_PLAN_MEDICATION.*_snapshot`. | Mapear a `TextField` (PostgreSQL `text`, sin límite) para no inventar una longitud. **Requiere decisión — DEC-01.** |
| **A-03** | `APPOINTMENT` tiene `priority` (enum), `priority_suggested_by_ai` (varchar 30) y `priority_final` (varchar 30). Los tres coexisten sin semántica documentada. | `priority_suggested_by_ai` = salida cruda de Gemini; `priority_final` = valor confirmado por el profesional; `priority` = enum operativo de la cita. Se implementan las tres columnas tal cual. **La regla de sincronización requiere decisión — DEC-02.** |
| **A-04** | `is_primary` declara "max 1 primary/patient" como texto libre. | `UniqueConstraint(fields=['patient'], condition=Q(is_primary=True), name='uq_patient_primary_pathology')` — índice único parcial. Traducción fiel de la regla escrita en el DER, no una adición. **Confirmar.** |
| **A-05** | `TREATMENT_PLAN.pathology_id` no lleva marca "FK" en el margen pero su tipo dice `bigint FK`. | Tratar como FK nullable a `PATHOLOGY`. |
| **A-06** | `datetime` sin precisar zona horaria en todo el DER. | `USE_TZ=True` → `timestamptz` en PostgreSQL (`DateTimeField`). Comportamiento por defecto del stack y el correcto para recordatorios. |
| **A-07** | `bool` en `PATIENT_PATHOLOGY.is_primary` (sin `NOT NULL`) frente a `boolean NOT NULL` en `PATIENT.is_active`. | `is_primary` → `BooleanField(null=True)`; `is_active` → `BooleanField()` con `default=True`. |
| **A-08** | El DER no indica comportamiento `ON DELETE` de ninguna FK. | Propuesta: `PROTECT` para FK de dominio hacia `PATIENT`/`PATHOLOGY`/`USER`; `CASCADE` para relaciones de composición (`CLINICAL_HISTORY→ENTRY/NOTE`, `TREATMENT_PLAN→MEDICATION`, `APPOINTMENT→REMINDER`, `IMPORT_BATCH→ROW`). **Requiere decisión — DEC-04.** |
| **A-09** | No se especifica si `PATIENT`/`PATHOLOGY` se borran físicamente. | `PATIENT` tiene `is_active` → baja lógica, nunca `DELETE`. `PATHOLOGY` no tiene campo de estado → no se expondrá endpoint de borrado. |

---

## 11. Desviaciones documentales menores (D-xx)

| ID | Descripción |
|---|---|
| **D-00** | El nombre del archivo del DER en la documentación (`...-1024.jpg`) no coincide con el del repositorio (`....png`). |
| **D-01** | `uq_patient_pathology` está dibujada como si fuera una columna. Se interpreta como declaración de restricción; **no** se creará una columna con ese nombre. |
| **D-02** | `APPOINTMENT_REMINDER` carece de `created_at`/`updated_at`/`created_by`/`updated_by`, mientras la documentación pide auditoría "como mínimo" en entidades críticas. Se respeta el DER: la tabla **no** heredará del modelo abstracto `Auditor`. |
| **D-03** | `AUDIT_LOG` no tiene columna `changes`, aunque la documentación pide poder conocer "cambios realizados". Se derivará en tiempo de lectura del diff `old_values`/`new_values`, sin añadir columna. |
| **D-04** | `IMPORT_BATCH_ROW` no tiene FK al `PATIENT` creado o encontrado. La trazabilidad fila → entidad será únicamente por `identification_number`. |
| **D-05** | La documentación describe `people` como "pacientes, historial clínico, patologías"; no menciona `NOTE`. Se asigna `NOTE` a `people` por su FK a `CLINICAL_HISTORY`. |
| **D-06** | La documentación no menciona `PATIENT_PATHOLOGY` en la carga masiva, pero es la única tabla donde puede materializarse "asociar patología" sin duplicados, gracias a `uq_patient_pathology`. |

---

## 12. Decisiones pendientes de aprobación

| ID | Decisión | Recomendación |
|---|---|---|
| **DEC-01** | Longitud de los `varchar` sin tamaño (A-02) | `TextField` sin longitud, fiel al DER |
| **DEC-02** | Semántica y sincronización de `priority` / `priority_suggested_by_ai` / `priority_final` (A-03) | Independientes; la IA sólo escribe `priority_suggested_by_ai` |
| **DEC-03** | Valores concretos de los 9 ENUM (sección 8) | **No inventarlos.** Se requiere la lista; propuesta en `IMPLEMENTATION_PLAN.md` §7 |
| **DEC-04** | Comportamiento `ON DELETE` de cada FK (A-08) | `PROTECT` en dominio, `CASCADE` en composición |
| **DEC-05** | Índices de rendimiento adicionales (búsqueda por nombre, filtro por fecha de cita) | Autorizar sólo índices no-únicos, que no alteran el contrato |
| **DEC-06** | Estrategia `USER` / JWT (C-02) | Opción 3: `AbstractBaseUser` sin `PermissionsMixin` (+2 columnas, 0 tablas) |
| **DEC-07** | Persistencia de la sugerencia de tratamiento IA (C-06) | No persistir; sólo respuesta de API |
| **DEC-08** | Usuario técnico `system` para auditoría de tareas automáticas (C-04) | Crear vía data migration |

---

## 13. Resumen de conformidad

- Tablas del DER: **14**. Todas serán implementadas; ninguna se fusiona ni se renombra.
- Columnas transcritas: **140**, incluyendo la fila de restricción `uq_patient_pathology`
  → **139 columnas físicas**. *(Corregido: una versión anterior de este documento decía
  131/130 por un error aritmético en el recuento. El conteo autoritativo es ahora
  `tests/der_inventory.py`, verificado por `tests/test_der_contract.py`.)*
- FK de dominio: **12**. FK de auditoría: **22**. Total: **34**.
- Restricciones UNIQUE: **6** declaradas + **1** regla textual (`is_primary`).
- Entidades añadidas respecto al DER: **0**.
- Entidades eliminadas respecto al DER: **0**.
- Campos añadidos respecto al DER: **0**, salvo lo que resuelva **DEC-06** (`password`,
  `last_login` en `USER`), que está bloqueado a la espera de autorización.
