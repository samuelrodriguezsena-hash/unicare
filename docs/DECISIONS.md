# UniCare — Registro de decisiones

**Autorización:** el responsable del proyecto autorizó explícitamente resolver las decisiones
pendientes de `DER_ANALYSIS.md` §12 y `IMPLEMENTATION_PLAN.md` §12, aplicando las
modificaciones necesarias.

Este documento es el registro vinculante de esas resoluciones. Cualquier implementación
posterior debe ajustarse a lo aquí escrito. Toda modificación al DER queda listada en §3.

---

## 1. Contradicciones resueltas

### C-01 — `PATIENT_MEDICAL_RECORD` vs `PATIENT_PATHOLOGY` → **RESUELTA**

**Decisión:** se implementa `PATIENT_PATHOLOGY` tal como aparece en el DER.
`PATIENT_MEDICAL_RECORD` se descarta: no existe en el diagrama y la propia documentación
declara que su lista de entidades "NO sustituye la inspección del archivo visual".

**Consecuencia:** el filtro "por patología principal", la asociación de patologías en la carga
masiva y el punto de partida de la sugerencia de tratamiento con IA se resuelven todos sobre
`PATIENT_PATHOLOGY`.

### C-02 / DEC-06 — `USER` y JWT → **RESUELTA (opción 3)**

**Decisión:** `core.User` hereda de `AbstractBaseUser` **sin** `PermissionsMixin`.

- Se añaden al DER exactamente **dos** columnas: `password` y `last_login` (ver §3).
- **No** se crean las tablas M2M `user_groups` ni `user_user_permissions`.
- **No** se añaden `is_staff` ni `is_superuser`.
- `django.contrib.admin` **no** se incluye en `INSTALLED_APPS`: sin `PermissionsMixin` el admin
  de Django no es utilizable, y el proyecto no lo requiere.
- `manage.py createsuperuser` sigue funcionando: el manager define `create_superuser()` como
  alias de `create_user()`. Dado que no existen roles (C-03), todo usuario activo tiene las
  mismas capacidades, por lo que "superusuario" y "usuario" son equivalentes en este sistema.
  La documentación de deployment lo indica explícitamente.

**Justificación:** delta mínimo verificable sobre el contrato (2 columnas, 0 tablas nuevas),
suficiente para `djangorestframework-simplejwt`.

### C-03 — Roles y autorización → **RESUELTA (opción 3)**

**Decisión:** autenticación obligatoria sin diferenciación por rol.

- Todos los endpoints de escritura sobre pacientes, tratamientos y citas exigen usuario
  autenticado y activo.
- La lógica de permisos vive aislada en `apps/core/permissions.py`, separada de la de negocio.
- **Limitación documentada:** no es posible distinguir "médico" de "administrativo" ni de
  ningún otro perfil. Añadir roles más adelante requiere una columna `role` en `USER` y es un
  cambio localizado en `permissions.py`.

### C-04 / DEC-08 — `AUDIT_LOG.user_id` NOT NULL → **RESUELTA**

**Decisión:** se crea un usuario técnico `system` mediante *data migration* en `core`.

- Cuando existe un usuario autenticado que origina la operación, se le atribuye a él.
- Cuando la operación proviene del planificador de Celery o de un comando de gestión, se
  atribuye al usuario `system`.
- `system` se crea con contraseña inutilizable (`set_unusable_password()`) y no puede
  autenticarse. Su nombre es configurable vía `SYSTEM_USERNAME`.
- **No se modifica la nulabilidad de `AUDIT_LOG.user_id`.**

### C-05 — Reintentos de recordatorios → **RESUELTA**

**Decisión:** los reintentos se implementan en la capa Celery (`autoretry_for`, `max_retries`,
backoff exponencial). **No se añade ninguna columna** a `APPOINTMENT_REMINDER`.

El resultado final se registra en las columnas que sí existen: `status`, `sent_at`,
`failure_reason`. La documentación condiciona el requisito a que el campo exista en el DER,
y no existe.

**Limitación documentada:** no habrá trazabilidad persistida del número de intentos; sólo la
que quede en los logs y en Sentry.

### C-06 / DEC-07 — Flujo de aprobación de IA → **RESUELTA**

**Decisión:** ninguna tabla nueva. El flujo se materializa con las columnas existentes:

| Sugerencia | Persistencia | Estado de aprobación |
|---|---|---|
| Prioridad de cita | `APPOINTMENT.priority_suggested_by_ai` | `priority_final` vacío = pendiente; con valor = validada por un profesional |
| Medicamento de un plan | `TREATMENT_PLAN_MEDICATION.validation_status` + `warning_flag` | `validation_status` |
| Resumen clínico | `CLINICAL_HISTORY.last_ai_summary` + `last_ai_summary_at` | Sin estado — es caché del último resumen |
| Sugerencia de tratamiento | **No se persiste** | El acto de aprobación es crear un `TREATMENT_PLAN_MEDICATION` a partir de ella |

**Limitación documentada:** no queda historial de sugerencias de tratamiento rechazadas.

### C-07 — URL de la API de fármacos → **RESUELTA parcialmente**

**Decisión:** `FARMACOS_API_BASE_URL` es una variable de entorno **obligatoria y sin valor por
defecto**. El placeholder `https://api.xxxxxx.com` no se escribe en ningún punto del código.

El cliente se implementa contra el contrato documentado y se ejercita **exclusivamente con
mocks**. No se ejecutará ninguna llamada real hasta disponer de la URL definitiva.

**Sigue abierto:** el objetivo no funcional de < 500 ms no es demostrable sin un endpoint real.

### C-08 — Patrón del SDK de Gemini → **RESUELTA (mitigada)**

**Decisión:** se usa el patrón exactamente como lo indica la documentación normativa
(`client.interactions.create(model=..., input=...)`), confinado a un único método privado
`GeminiService._invoke()`. El modelo se lee de `GEMINI_MODEL`, con default `gemini-3.7-flash`.

Si al ejecutar contra el SDK real la firma resultara distinta, el ajuste queda contenido en ese
método y no afecta a servicios, vistas ni tests (que mockean esa frontera).

---

## 2. Decisiones técnicas resueltas

| ID | Decisión tomada |
|---|---|
| **DEC-01** | `varchar` sin longitud → `TextField` (`text` en PostgreSQL). Afecta a `PATIENT.identification_number`, `USER.username`, `USER.email` y los dos `*_snapshot` de `TREATMENT_PLAN_MEDICATION`. No se inventan longitudes. **`USER.email` usa `TextField` + `EmailValidator`, no `EmailField`**: `EmailField` impone un `max_length=254` propio de Django que el DER no declara. En `PATIENT.email` sí se usa `EmailField(max_length=255)`, porque ahí el DER **sí** declara `varchar(255)`. |
| **DEC-02** | `priority`, `priority_suggested_by_ai` y `priority_final` son independientes. La IA escribe **únicamente** `priority_suggested_by_ai`. `priority_final` sólo lo escribe un profesional vía `POST appointments/{id}/priority/`. `priority` es el enum operativo de la cita y no se deriva automáticamente de la IA. |
| **DEC-03** | Valores de los enums fijados en §4. |
| **DEC-04** | `ON DELETE`: `PROTECT` en FK de dominio (`PATIENT`, `PATHOLOGY`); `CASCADE` en composición (`CLINICAL_HISTORY→ENTRY/NOTE`, `TREATMENT_PLAN→MEDICATION`, `APPOINTMENT→REMINDER`, `IMPORT_BATCH→ROW`); `SET_NULL` en `created_by`/`updated_by` (el DER los declara nullable); `PROTECT` en `AUDIT_LOG.user_id` (es NOT NULL: un usuario con auditoría no se puede borrar). |
| **DEC-05** | Se autorizan índices **no únicos** en: `patient(last_name, first_name)`, `patient(is_active)`, `appointment(scheduled_at)`, `appointment(patient_id, scheduled_at)`, `appointment_reminder(status, scheduled_at)`, `audit_log(entity_type, entity_id)`, `audit_log(created_at)`. Ninguno altera el contrato del DER. |
| **DEC-09** | `db_table` en minúsculas (`patient`, `clinical_history`, …). Para PostgreSQL sin comillas es el mismo identificador que el del DER en mayúsculas. |
| **DEC-10** | Los `enum(...)` se implementan como `CharField` + `TextChoices` + `CheckConstraint`, no como tipos `ENUM` nativos de PostgreSQL. Preserva el dominio cerrado y mantiene las migraciones reproducibles. |
| **DEC-11** | `beat_schedule` estático de Celery, **no** `django-celery-beat` (crearía 6 tablas fuera del DER). |
| **DEC-12** | `USE_TZ = True` → `timestamptz`. Zona horaria por defecto `UTC`, configurable con `DJANGO_TIME_ZONE`. |
| **DEC-13** | Imagen base Docker `python:3.12-slim`, que es el mínimo que exige el stack. |
| **DEC-14** | `USER` → `db_table = "user"`. `user` es **palabra reservada** en PostgreSQL, pero Django entrecomilla todos los identificadores (`CREATE TABLE "user"`), por lo que funciona. **Consecuencia operativa:** cualquier SQL escrito a mano contra esta tabla debe entrecomillarla. Se respeta el nombre del DER en lugar de renombrarla. |
| **DEC-15** | `django.contrib.admin` **no** se instala. Sin `PermissionsMixin` el admin no es utilizable (exige `is_staff` y `has_perm`), y el proyecto no lo requiere. La administración se hace por API. |
| **DEC-17** | El DER y la documentación funcional **no definen el formato del número de identificación**. No se inventa uno rígido: `IDENTIFICATION_NUMBER_PATTERN` es configurable y su valor por defecto (`^[A-Za-z0-9][A-Za-z0-9.\-]{1,49}$`) sólo descarta lo inequívocamente inválido (vacío, espacios internos, símbolos raros). **Ajustar si la normativa local exige un formato concreto.** |
| **DEC-18** | En un `UPDATE`, `AUDIT_LOG.old_values`/`new_values` guardan **sólo las columnas que cambiaron**, no la instantánea completa. El DER no obliga a lo segundo, y así `AUDIT_LOG` responde directamente a "qué se modificó" sin inflar el jsonb en cada guardado. En `CREATE` y `DELETE` sí se guarda el estado completo. |
| **DEC-38** | La suite **bloquea las conexiones de red** a nivel de socket (`tests/conftest.py`), permitiendo sólo loopback. Confiar en que cada test recuerde mockear no basta: un mock olvidado haría la suite lenta, no determinista y podría mandar datos de prueba a un tercero. |
| **DEC-39** | En producción, `DJANGO_ALLOWED_HOSTS` vacía **aborta el arranque**. `env()` sólo protesta si la variable falta; una cadena vacía dejaría `ALLOWED_HOSTS=[]` y Django respondería 400 a todo. Es preferible fallar al arrancar con un mensaje claro. |
| **DEC-36** | **`max_request_body_size="never"` en Sentry.** El valor por defecto de `sentry-sdk` es `"medium"`, que **sí envía el cuerpo de la petición** pese a `send_default_pii=False` — es decir, diagnósticos y notas clínicas saldrían a un tercero. Además, un `before_send` propio elimina cabeceras, cookies y query string, reduce el usuario a su ID y redacta claves sensibles y clínicas por coincidencia parcial. |
| **DEC-37** | El detalle de **qué** se modificó vive en `AUDIT_LOG`, dentro de nuestra base, y **no** se envía a Sentry. A Sentry sólo va lo necesario para diagnosticar el fallo: excepción, endpoint e ID de usuario. |
| **DEC-35** | **Ni rotación de refresh tokens ni lista negra.** `ROTATE_REFRESH_TOKENS=True` hace que simplejwt escriba en `OutstandingToken`, de la app `token_blacklist`, que añade **dos tablas fuera del DER**; sin esa app, refrescar responde 500. Consecuencia asumida: un refresh token no se puede revocar antes de caducar, el "logout" es del lado del cliente, y la mitigación es la vida corta de los tokens (15 min el access). |
| **DEC-32** | El DER **no define ninguna columna donde guardar el archivo** de carga masiva, sólo `source_file_name` y `source_file_type`. En vez de añadir una, el archivo se parsea al subirlo y cada línea se persiste como `IMPORT_BATCH_ROW`, que ya tiene los snapshots necesarios. El archivo no se retiene: las filas son el estado intermedio. |
| **DEC-33** | Ni el DER ni la documentación funcional definen las **columnas del archivo**. Se fija un contrato mínimo (`identification_number`, `first_name`, `last_name`, `pathology` obligatorias; resto opcionales) alineado con los snapshots de `IMPORT_BATCH_ROW`. **Requiere confirmación.** |
| **DEC-34** | Si una fila pide `is_primary` y el paciente ya tiene patología principal, la patología **se asocia igual pero como secundaria**. El DER sólo admite una principal; perder la fila entera sería peor que registrarla sin marcar. |
| **DEC-29** | El DER declara `APPOINTMENT_REMINDER.channel` nullable y no dice cómo elegirlo. Se usa `EMAIL` si el paciente tiene email, `SMS` si sólo tiene teléfono, y **no se programan recordatorios** si no tiene ningún contacto: programar algo que no se puede entregar sólo genera fallos. |
| **DEC-30** | Al reprogramar una cita se descartan los recordatorios **pendientes** y se rehacen con la nueva fecha. Los ya enviados **no se tocan**: son historia de lo que el paciente recibió. |
| **DEC-31** | Las tareas se encolan con `transaction.on_commit`, no de inmediato: si no, el worker podría leer la cita antes de que la transacción se confirme y no encontrarla. |
| **DEC-26** | Un fallo de la IA al priorizar **no impide agendar la cita**: `priority_suggested_by_ai` queda vacío y la cita se crea igual. Es lo contrario de DEC-21 (medicamentos) porque allí el dato externo forma parte de la integridad del registro, mientras que aquí la sugerencia es orientativa. Agendar es la operación clínica; priorizar es apoyo. |
| **DEC-27** | El endpoint de confirmación profesional escribe `priority_final` **y** `priority`. DEC-02 impide que *la IA* escriba esos campos, no que lo haga un profesional de forma explícita. La sugerencia original se conserva para no perder la trazabilidad cuando el profesional discrepa. |
| **DEC-28** | Los eventos de calendario **no llevan `end`**: `APPOINTMENT` define `scheduled_at` pero no duración ni hora de fin. Inventar una duración por defecto sería añadir información clínica que el DER no contiene. |
| **DEC-23** | Toda salida de Gemini pasa por `ai_envelope()`, que añade etiqueta, advertencia, `status: PENDIENTE_DE_VALIDACION`, versión del prompt y modelo. Ninguna salida de IA puede llegar al cliente sin ese envoltorio. |
| **DEC-24** | Una respuesta del modelo que no cumple el formato declarado es un **error de integración (502), nunca un resultado**. Devolver texto libre como si fuera una sugerencia estructurada sería peor que fallar. |
| **DEC-25** | Al construir el contexto que se envía a Gemini se excluyen identificación, teléfono, email, dirección y apellidos del paciente: el modelo no los necesita. Hay tests que fallan si aparecen. |
| **DEC-20** | **La API externa de fármacos NO publica ningún campo identificador**: sus cinco campos son atributos, no claves. `TREATMENT_PLAN_MEDICATION.external_medication_id` (varchar 100 NOT NULL en el DER) se interpreta como el `Nombre_Medicamento` publicado por esa API, que es el único identificador natural disponible. **Si la API real llegara a exponer un ID propio, este mapeo debe revisarse.** |
| **DEC-21** | Si la API externa no responde al asociar un medicamento, **la operación falla (502) y no se guarda nada**. Sin la fuente externa no hay snapshot ni validación cruzada, y persistir información clínica sin validar sería peor que fallar. Es distinto de una *discrepancia*, que sí se acepta con advertencia. |
| **DEC-22** | `external_medication_id` **no es modificable** una vez asociado el medicamento: cambiarlo invalidaría los snapshots y la validación cruzada ya registrados. Para cambiar de fármaco se quita y se asocia otro. |
| **DEC-19** | Un fallo al escribir la auditoría **no propaga la excepción**: se registra y se reporta a Sentry, pero la operación de negocio continúa. Perder una entrada de auditoría es malo; perder el dato clínico, peor. |
| **DEC-16** | Pin de `psycopg[binary]` elevado de `3.2.9` a `3.2.13`: la 3.2.9 no publica wheel para Python 3.14, que es el intérprete disponible en la máquina de desarrollo. La versión es compatible con el 3.12 del contenedor. |
| **DEC-40** | En producción se añaden `localhost` y `127.0.0.1` a `ALLOWED_HOSTS`. Las sondas locales (el `HEALTHCHECK` del contenedor, las probes de un orquestador) llegan con ese `Host`, y sin esto Django respondía **400** a todas: el contenedor quedaba *unhealthy* para siempre estando sano. No debilita nada — `ALLOWED_HOSTS` protege las URLs absolutas que genera el servidor, y quien mande `Host: localhost` sólo se envenena sus propios enlaces de paginación. |
| **DEC-41** | Los dos health checks quedan **exentos del redirect a HTTPS** (`SECURE_REDIRECT_EXEMPT`). Una sonda local habla HTTP plano: sin la exención recibía un **301** que `curl -f` y las probes de los orquestadores dan por bueno, así que la sonda pasaba sin haber llegado nunca a la vista. Aparentar salud es peor que fallar. Ambos endpoints son públicos y no devuelven información clínica. |
| **DEC-42** | El `HEALTHCHECK` de la imagen es `scripts/healthcheck.py` (stdlib), no `curl`. Dos motivos: `curl` era el único paquete de sistema extra en la imagen de runtime, y `curl -f` **no falla ante un 3xx**. Sólo el 200 cuenta como sano. Comprueba **liveness**: una caída de PostgreSQL no se arregla reiniciando el contenedor. |
| **DEC-43** | En producción la API responde **sólo JSON**: el navegador de DRF es una herramienta de desarrollo que renderiza formularios de escritura para cada endpoint. Al quitarlo desaparece el único consumidor de ficheros estáticos del proyecto (el admin de Django no está instalado), así que `collectstatic` pasa a estar **desactivado por defecto** en el entrypoint (`COLLECT_STATIC=1` lo reactiva). |
| **DEC-44** | El log de acceso de gunicorn usa un formato propio que **omite la query string**. El formato por defecto registra la línea de petición completa (`RAW_URI`), así que `?search=Juan+Perez` de una búsqueda de pacientes acabaría escrito en el log de cada petición. Se registra la ruta (`PATH_INFO`), que es lo útil para operar. |
| **DEC-45** | En `docker-compose.prod.yml` **PostgreSQL es externo** y se configura con `DATABASE_URL`: en producción la base necesita copias de seguridad, actualizaciones y persistencia que no deben depender del ciclo de vida de un compose. Para un despliegue en una sola máquina hay un servicio `db` bajo el perfil `db-local`. |
| **DEC-46** | `.gitignore` y `.dockerignore` pasan de ignorar `.env` a ignorar `.env.*` (con `!.env.example`). El patrón anterior **no cubría `.env.production`**, que se habría versionado y, peor, horneado en la imagen: credenciales de producción distribuidas con cada `docker push`. |

---

## 3. Modificaciones al DER (registro exhaustivo)

Estas son **todas** las desviaciones respecto al diagrama. No hay ninguna otra.

| # | Tabla | Cambio | Motivo | Autorización |
|---|---|---|---|---|
| 1 | `USER` | + columna `password` (`varchar(128) NOT NULL`) | Requisito insalvable de `AbstractBaseUser` y de JWT | C-02, opción 3 |
| 2 | `USER` | + columna `last_login` (`timestamptz NULL`) | Requisito insalvable de `AbstractBaseUser` | C-02, opción 3 |

- Entidades añadidas: **0**
- Entidades eliminadas: **0**
- Entidades renombradas o fusionadas: **0**
- Relaciones añadidas, eliminadas o alteradas: **0**
- Restricciones UNIQUE añadidas o eliminadas: **0**
- Nulabilidad alterada: **0**
- Tipos alterados: **0**

La restricción única parcial `uq_patient_primary_pathology` **no** cuenta como adición: es la
traducción literal de la regla `"bool; max 1 primary/patient"` escrita dentro del propio DER.

---

## 4. Dominio de valores de los enums (DEC-03)

Los valores se derivan de la documentación funcional donde ésta los nombra (prioridades de
cita, canales de notificación, estados de importación); en el resto se elige el conjunto mínimo
suficiente para los flujos exigidos. Se declaran aquí para que sean revisables.

| Tabla | Columna | Valores |
|---|---|---|
| `CLINICAL_HISTORY_ENTRY` | `entry_type` | `DIAGNOSIS`, `TREATMENT`, `OBSERVATION`, `PROCEDURE`, `FOLLOW_UP` |
| `APPOINTMENT` | `status` | `SCHEDULED`, `CONFIRMED`, `COMPLETED`, `CANCELLED`, `NO_SHOW` |
| `APPOINTMENT` | `priority` | `URGENT`, `ROUTINE_CONTROL`, `POST_OPERATIVE` *(de la documentación: "Urgente", "Control de Rutina", "Post-operatorio")* |
| `APPOINTMENT_REMINDER` | `channel` | `EMAIL`, `SMS` *(de la documentación: "posteriormente integrar email, SMS")* |
| `APPOINTMENT_REMINDER` | `status` | `PENDING`, `SENT`, `FAILED` |
| `TREATMENT_PLAN` | `status` | `DRAFT`, `ACTIVE`, `COMPLETED`, `CANCELLED` |
| `AUDIT_LOG` | `action` | `CREATE`, `UPDATE`, `DELETE` |
| `IMPORT_BATCH` | `status` | `PENDING`, `PROCESSING`, `COMPLETED`, `COMPLETED_WITH_ERRORS`, `FAILED` |
| `IMPORT_BATCH_ROW` | `status` | `PENDING`, `SUCCESS`, `ERROR` |

`TREATMENT_PLAN_MEDICATION.validation_status` es `varchar(30)` en el DER, **no** un enum.
Se implementa como `TextChoices` a nivel de aplicación (`PENDING`, `VALIDATED`, `WARNING`)
**sin** `CheckConstraint`, para no imponer una restricción que el DER no declara.

---

## 5. Decisiones que siguen abiertas

| Tema | Estado |
|---|---|
| URL real de la API de fármacos (C-07) | **Pendiente de terceros.** Sólo mocks hasta recibirla |
| Verificación del patrón del SDK de Gemini (C-08) | **Mitigada**, no verificada. Confinada a `GeminiService._invoke()` |
| Objetivo de < 500 ms en llamadas externas | **No demostrable** sin endpoint real |
