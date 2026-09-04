# Testing

**955 tests, 100 % de cobertura.** El gate obligatorio es del 85 %.

```bash
python -m pytest --cov
```

```bash
python -m pytest -q --no-cov          # rápido, sin cobertura
python -m pytest tests/test_audit.py -v
```

## Dos modos de ejecución

| Modo | Tests | Qué verifica |
|---|---|---|
| **Con PostgreSQL** | 955 | Todo |
| **Sin PostgreSQL** | ~470 | Contrato del DER, migraciones, prompts, saneado de Sentry, validadores, parsers, contenedor |

Los módulos que necesitan base se saltan solos (`tests/db.py`). **Que un módulo se salte no es lo
mismo que que pase**: el mensaje del skip lo dice explícitamente.

Levantar la base: `docker compose up -d db`, o ver
[`DEV_POSTGRES_SIN_DOCKER.md`](DEV_POSTGRES_SIN_DOCKER.md).

## Ningún test sale a la red

`tests/conftest.py` intercepta `socket.connect` durante toda la sesión y **bloquea cualquier
destino que no sea loopback**.

Confiar en que cada test recuerde mockear no basta: un `respx.mock` olvidado o una dependencia
que llame a casa pasarían desapercibidos, harían la suite lenta y no determinista, y en el peor
caso mandarían datos de prueba a un tercero.

Las dos integraciones externas se doblan siempre:

| Integración | Doble |
|---|---|
| API de fármacos (`httpx`) | `respx`, que intercepta el transporte |
| SDK de Gemini | `GeminiFalso`, que sustituye `_invoke()` |

Hay un test que comprueba que la salvaguarda está activa y que **de verdad bloquea** una
conexión saliente.

## El gate de cobertura

Configurado en `pyproject.toml` (`fail_under = 85`) y verificado: hay tests que comprueban que
`coverage` **sale con código 2 cuando no se alcanza** y con 0 cuando sí. Un umbral que no
bloquea nada no es un gate.

## Qué se prueba

| Área | Módulo |
|---|---|
| Contrato del DER: tablas, columnas, nulabilidad, FK, UNIQUE | `test_der_contract.py` |
| Migraciones sincronizadas con los modelos | `test_migrations.py` |
| Esquema físico en PostgreSQL y sus restricciones | `test_schema_postgresql.py` |
| Pacientes: CRUD, búsqueda, filtros, historial | `test_people_api.py` |
| Planes de tratamiento y validación cruzada | `test_treatment_plans.py` |
| Agenda, calendario y priorización | `test_appointments_api.py`, `test_appointment_priority.py` |
| Recordatorios y tareas Celery | `test_reminders.py` |
| Carga masiva CSV/XLSX | `test_massive_load.py` |
| API externa de fármacos | `test_farmacos_api.py` |
| Gemini y endpoints de IA | `test_gemini_service.py`, `test_ai_endpoints.py` |
| Auditoría | `test_audit.py`, `test_audit_api.py` |
| JWT y permisos | `test_jwt_auth.py`, `test_permissions_coverage.py` |
| Sentry y saneado | `test_observability.py` |
| Contenedor de produccion: sonda, entrypoint, compose | `test_docker.py` |
| Garantías de la propia suite | `test_suite_guarantees.py` |

### Tests que vigilan propiedades, no funciones

Algunos no prueban un caso concreto sino una **invariante del proyecto**, y fallan aunque nadie
escriba un test específico:

- **Ningún endpoint queda desprotegido** — recorre el URLconf entero
  (`test_permissions_coverage.py`). Comprobado que detecta un endpoint desprotegido.
- **Ninguna entidad fuera del DER** — falla si aparece un modelo, tabla o M2M nuevo.
- **El SDK de Gemini sólo se importa en un archivo.**
- **`appointments` no conoce ningún proveedor de email/SMS.**
- **`medications` no tiene catálogo local de fármacos.**
- **El worker descubre sus tareas** — en un intérprete aparte, porque dentro de la suite el
  registro ya está poblado.
- **`development` y `production` se importan sin error** — en subprocesos, porque los tests usan
  `testing` y un fallo ahí sólo aparecería al desplegar.
- **No hay secretos hardcodeados** — DSN de Sentry, URLs externas.
- **La sonda de salud del contenedor recibe un 200 de verdad** — llamando a la
  aplicación WSGI con las settings de **producción** en otro proceso. Detectó dos
  fallos reales que dejaban el contenedor *unhealthy* para siempre (DEC-40, DEC-41).
- **El log de acceso no registra la query string** — verificado con el formateador
  de gunicorn, no leyendo la cadena de formato.

## Herramientas

`pytest`, `pytest-django`, `pytest-cov`, `coverage`, `respx` y `factory-boy`.

`tests/factories.py` cubre las 13 entidades. Se usan donde hace falta **población** (N+1,
paginación, filtros); los tests de una regla concreta construyen sus datos a mano, porque ahí
ver el dato exacto es parte del test.

## Notas de mantenimiento

- **`on_commit`**: los tests corren en una transacción que se revierte, así que las tareas
  encoladas con `transaction.on_commit` no se ejecutan salvo que se capturen con
  `django_capture_on_commit_callbacks`. Es lo que evita que la suite genere recordatorios sin
  querer.
- **`force_authenticate` salta la autenticación.** Sólo `test_jwt_auth.py` ejercita el camino
  real de JWT; conviene recordarlo antes de concluir que "la autenticación está probada".
- **Nada de fechas fijas.** Los tests de edad y de agenda calculan sus fechas relativas a hoy,
  para que no empiecen a fallar solos con el paso del tiempo.
