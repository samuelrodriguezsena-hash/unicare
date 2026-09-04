# UniCare — Backend

Plataforma backend para la gestión simplificada de pacientes oncológicos.
Django 5.2 · DRF · PostgreSQL · Redis · Celery · Docker.

> El **DER** ([`docs/DER.png`](docs/DER.png)) es el contrato del modelo de datos.
> Antes de tocar modelos, lee [`docs/DER_ANALYSIS.md`](docs/DER_ANALYSIS.md) y
> [`docs/DECISIONS.md`](docs/DECISIONS.md).

## Estado

| Fase | Estado |
|---|---|
| 0 — Inspección del DER | Completa |
| 1 — Bootstrap Django | Completa |
| 2 — PostgreSQL / Redis / Celery / Docker | Completa |
| 3 — Modelos según el DER | Completa (14/14 entidades) |
| 4 — Migraciones | Completa: aplicadas y verificadas contra PostgreSQL 16.4 |
| 7 — Integración API de fármacos | Completa (consulta en tiempo real) |
| 5 — Core, auditoría y utilidades | Completa |
| 6 — People (pacientes, historial, patologías) | Completa |
| 8 — Medications (planes de tratamiento) | Completa |
| 9 — Gemini (resumen clínico y sugerencias) | Completa |
| 10 — Appointments (agenda, calendario, prioridad IA) | Completa |
| 11 — Celery y recordatorios | Completa |
| 12 — Carga masiva CSV/XLSX | Completa |
| 13 — JWT y permisos | Completa |
| 14 — Sentry y observabilidad | Completa |
| 15 — Tests y gate de cobertura | Completa (100 %) |
| 16 — CI | Completa |
| 17 — Docker de producción | Completa |
| 18 — Documentación de despliegue | Completa |

## Arranque en desarrollo

```bash
cp .env.example .env
```

Edita `.env` y genera una `DJANGO_SECRET_KEY` real:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

Levanta el stack:

```bash
docker compose up --build
```

Aplica las migraciones:

```bash
docker compose exec web python manage.py migrate
```

Con la base levantada se activan además los tests de esquema físico, que se
saltan cuando no hay PostgreSQL accesible:

```bash
python -m pytest tests/test_schema_postgresql.py -v
```

Crea un usuario:

```bash
docker compose exec web python manage.py createsuperuser
```

> No existen roles (ver `docs/DECISIONS.md`, C-03): todo usuario activo tiene
> las mismas capacidades. `createsuperuser` crea un usuario normal.

Comprueba que responde:

```bash
curl http://localhost:8000/api/v1/health/ready/
```

## Endpoints disponibles

| Método | Ruta | Auth | Descripción |
|---|---|---|---|
| POST | `/api/v1/auth/token/` | No | Obtener token JWT — ver [`docs/AUTENTICACION.md`](docs/AUTENTICACION.md) |
| POST | `/api/v1/auth/token/refresh/` | No | Renovar el access token |
| GET | `/api/v1/health/` | No | Liveness |
| GET | `/api/v1/health/ready/` | No | Readiness: PostgreSQL y Redis |
| GET/POST | `/api/v1/patients/` | JWT | Pacientes: listado, búsqueda, filtros y alta — ver [`docs/API_PEOPLE.md`](docs/API_PEOPLE.md) |
| GET/PATCH | `/api/v1/patients/{id}/` | JWT | Detalle y modificación |
| POST | `/api/v1/patients/{id}/deactivate/` | JWT | Baja lógica |
| GET | `/api/v1/patients/{id}/clinical-history/` | JWT | Historial clínico |
| GET/POST | `/api/v1/patients/{id}/pathologies/` | JWT | Patologías del paciente |
| GET/POST | `/api/v1/pathologies/` | JWT | Catálogo de patologías |
| GET/POST | `/api/v1/treatment-plans/` | JWT | Planes de tratamiento — ver [`docs/API_MEDICATIONS.md`](docs/API_MEDICATIONS.md) |
| GET/POST | `/api/v1/treatment-plans/{id}/medications/` | JWT | Medicamentos del plan, con validación cruzada |
| GET | `/api/v1/treatment-plan-medications/{id}/alternatives/` | JWT | Alternativas de la misma familia |
| POST | `/api/v1/import-batches/` | JWT | Carga masiva CSV/XLSX — ver [`docs/CARGA_MASIVA.md`](docs/CARGA_MASIVA.md) |
| GET | `/api/v1/import-batches/{id}/report/` | JWT | Reporte de importación |
| GET/POST | `/api/v1/appointments/` | JWT | Agenda de citas — ver [`docs/API_APPOINTMENTS.md`](docs/API_APPOINTMENTS.md) |
| POST | `/api/v1/appointments/{id}/priority/` | JWT | Confirmación profesional de la prioridad |
| GET | `/api/v1/appointments/calendar/` | JWT | Eventos para calendario (día/semana/mes) |
| POST | `/api/v1/patients/{id}/ai-summary/` | JWT | Resumen clínico con IA — ver [`docs/IA.md`](docs/IA.md) |
| POST | `/api/v1/treatment-suggestions/` | JWT | Sugerencia de tratamiento con IA (no se persiste) |
| GET | `/api/v1/farmacos/` | JWT | Consulta la API externa de fármacos — ver [`docs/API_FARMACOS.md`](docs/API_FARMACOS.md) |
| GET | `/api/v1/audit-logs/` | JWT | Auditoría: listado filtrable — ver [`docs/AUDITORIA.md`](docs/AUDITORIA.md) |
| GET | `/api/v1/audit-logs/{id}/` | JWT | Auditoría: detalle |
| GET | `/api/v1/audit-logs/export/` | JWT | Auditoría: exportación CSV |

## Sin Docker

Requiere PostgreSQL y Redis accesibles, y `DATABASE_URL` / `REDIS_URL` apuntando a ellos.

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -r requirements/development.txt
```

```bash
python manage.py runserver
```

## Calidad

```bash
python -m pytest --cov --cov-report=term-missing
```

```bash
python -m black . && python -m ruff check --fix . && python -m flake8 .
```

Los mismos pasos que ejecuta el pipeline, en local:

```bash
scripts/ci.sh
```

El gate de cobertura es **85 %** (`pyproject.toml`); la cobertura actual es del **100 %** sobre
971 tests. Ver [`docs/TESTING.md`](docs/TESTING.md).

`tests/test_der_contract.py` compara los modelos, columna por columna, contra el inventario
del DER en `tests/der_inventory.py`. **Si falla, se corrige el modelo, no el test** — salvo que
la desviación se autorice en `docs/DECISIONS.md` §3.

## Estructura

```
config/          settings por entorno, urls, wsgi/asgi, celery
apps/core/       User, auditoría, utilidades, clientes compartidos
apps/people/     pacientes, historial clínico, patologías
apps/medications/ planes de tratamiento, API externa de fármacos
apps/appointments/ agenda, citas, recordatorios
apps/massive_load/ importación CSV/XLSX
docs/            análisis del DER, plan, decisiones, trazabilidad
scripts/         entrypoint del contenedor
tests/           suite transversal
```

## Documentación

- [`docs/DER_ANALYSIS.md`](docs/DER_ANALYSIS.md) — inventario del DER, contradicciones y ambigüedades
- [`docs/DECISIONS.md`](docs/DECISIONS.md) — decisiones tomadas y las **2** modificaciones al DER
- [`docs/IMPLEMENTATION_PLAN.md`](docs/IMPLEMENTATION_PLAN.md) — plan de implementación
- [`docs/TRACEABILITY_MATRIX.md`](docs/TRACEABILITY_MATRIX.md) — DER → modelo → app → API → tests
- [`docs/API_FARMACOS.md`](docs/API_FARMACOS.md) — endpoint `GET /api/v1/farmacos/`: filtros, respuestas, errores y variables
- [`docs/API_PEOPLE.md`](docs/API_PEOPLE.md) — pacientes, historial clínico y patologías
- [`docs/API_MEDICATIONS.md`](docs/API_MEDICATIONS.md) — planes de tratamiento, validación cruzada y alternativas
- [`docs/API_APPOINTMENTS.md`](docs/API_APPOINTMENTS.md) — agenda, calendario y priorización con IA
- [`docs/CARGA_MASIVA.md`](docs/CARGA_MASIVA.md) — importación CSV/XLSX, reglas por fila y reporte
- [`docs/RECORDATORIOS.md`](docs/RECORDATORIOS.md) — recordatorios a −48 h/−24 h, tareas Celery y notificaciones
- [`docs/IA.md`](docs/IA.md) — integración con Gemini: prompts, validación, privacidad y aislamiento del SDK
- [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) — puesta en producción paso a paso, rollback y problemas frecuentes
- [`docs/DOCKER.md`](docs/DOCKER.md) — imagen, roles del contenedor, stack de producción y qué está verificado
- [`docs/CI.md`](docs/CI.md) — pipeline, qué lo hace fallar y cómo ejecutarlo en local
- [`docs/TESTING.md`](docs/TESTING.md) — cómo se ejecuta la suite, qué garantiza y cómo mantenerla
- [`docs/OBSERVABILIDAD.md`](docs/OBSERVABILIDAD.md) — Sentry, saneado de datos clínicos y trazabilidad
- [`docs/AUTENTICACION.md`](docs/AUTENTICACION.md) — JWT, política de permisos y garantía de cobertura
- [`docs/AUDITORIA.md`](docs/AUDITORIA.md) — qué se registra, cómo funciona y endpoints de consulta
- [`docs/DEV_POSTGRES_SIN_DOCKER.md`](docs/DEV_POSTGRES_SIN_DOCKER.md) — PostgreSQL local cuando Docker no está disponible

## Seguridad

Cero secretos en el repositorio. `.env` está en `.gitignore` y nunca debe versionarse.
`GEMINI_API_KEY`, `SENTRY_DSN` y las credenciales de PostgreSQL se leen siempre del entorno.
