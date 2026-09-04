# Integración continua

`.github/workflows/ci.yml` — GitHub Actions. Se dispara en cada push, en cada pull request y a
mano (`workflow_dispatch`).

## Los tres jobs

| Job | Qué hace | Depende de |
|---|---|---|
| **calidad** | Formato, lint, checks de Django, migraciones, tests y cobertura | — |
| **configuracion-de-produccion** | `check --deploy` con las settings de producción | — |
| **imagen** | Build de la imagen y comprobación de que arranca | los dos anteriores |

Los dos primeros corren en paralelo. **La imagen sólo se construye si el código ya pasó**:
construir una imagen de código roto no aporta nada.

### calidad

```
black --check --diff .
ruff check --output-format=github .
flake8 .
manage.py check
manage.py makemigrations --check --dry-run
pytest --cov --cov-report=term-missing --cov-report=xml
coverage report --fail-under=85
```

Formato y lint van **antes** que los tests: son segundos, y un fallo ahí no merece esperar a la
suite entera.

`makemigrations --check` detecta un modelo cambiado sin su migración. Hay además un test que lo
cubre (`test_migrations.py`), pero como paso propio el fallo se lee de un vistazo.

PostgreSQL 16 se levanta como *service* con healthcheck — la misma versión que
`docker-compose` y que el entorno de verificación local. El informe de cobertura se publica
como artefacto.

### configuracion-de-produccion

Los tests usan `config.settings.testing`. Un error en las settings de **producción** sólo
aparecería al desplegar, así que se comprueban aparte con `check --deploy --fail-level WARNING`:
cualquier aviso de seguridad de Django tumba el pipeline.

El mismo job valida `docker-compose.prod.yml` con `docker compose config`, que resuelve el
fichero **sin tocar el daemon**: detecta una clave mal escrita o una variable sin definir antes
de que lo haga un despliegue.

### imagen

Build con `buildx` y caché de GitHub Actions, y tres comprobaciones: que el intérprete de la
imagen importa Django, que el entrypoint es ejecutable y —la que de verdad importa— que el
contenedor **arranca y su propio HEALTHCHECK lo declara sano**. Eso último ejercita gunicorn, el
entrypoint, las settings de producción y la sonda a la vez, y es lo único que no se puede
comprobar sin construir la imagen. No necesita PostgreSQL: la liveness no toca la base.

## El pipeline falla si…

| Causa | Paso |
|---|---|
| El formato no es el esperado | `black --check` |
| Lint | `ruff` / `flake8` |
| Algún test falla | `pytest` |
| La cobertura baja del 85 % | `coverage report --fail-under=85` |
| Falta una migración | `makemigrations --check` |
| Las settings de producción dan aviso de seguridad | `check --deploy` |
| La imagen no construye, no arranca o no se declara sana | job `imagen` |
| El compose de producción no resuelve | `docker compose config` |

### Un fallo que tenía el propio pipeline

El paso `check --deploy` corre con `--fail-level WARNING`, y su clave de ejemplo tenía 35
caracteres. Django emite `security.W009` por debajo de 50, así que **el job habría fallado en su
primera ejecución** — y, como el proyecto todavía no es un repositorio git, nadie lo habría visto
hasta entonces. Apareció al ensayar el despliegue (ver [`DEPLOYMENT.md`](DEPLOYMENT.md)).

Corregido, y cubierto por un test que ejecuta `check --deploy` con **el entorno leído del propio
workflow**, no con una copia: así sigue valiendo cuando alguien lo cambie.

**Comprobado, no supuesto:** se introdujeron defectos controlados (formato incorrecto, import
sin usar, un test que falla) y el pipeline los rechazó los tres, saliendo con código distinto de
cero. El gate de cobertura se verifica además en `tests/test_suite_guarantees.py`, midiendo un
subconjunto mínimo real y comprobando que `coverage` sale con código 2.

## Ejecutarlo en local

```bash
scripts/ci.sh
```

```bash
scripts/ci.sh --con-docker
```

Ejecuta **los mismos pasos**, para no descubrir en CI algo que se podía haber visto antes de
subir. Requiere PostgreSQL accesible vía `DATABASE_URL` (ver [`TESTING.md`](TESTING.md)).

Devuelve como código de salida el número de pasos fallidos, y no se detiene en el primero: así
un solo pase muestra todo lo que hay que arreglar.

## Configuración

El pipeline **no necesita ningún secreto**. Los valores de entorno están en el propio workflow y
ninguno es real:

| Variable | Valor en CI |
|---|---|
| `DATABASE_URL` | El service de PostgreSQL |
| `FARMACOS_API_BASE_URL` | `https://farmacos.invalid` — nunca se llama |
| `GEMINI_API_KEY` | Vacía |
| `SENTRY_DSN` | Vacía |

Las integraciones externas están mockeadas y la suite **bloquea las conexiones de red** a nivel
de socket, así que el pipeline es determinista y no depende de terceros.

## Ejecutado en el runner

El pipeline se ejecutó por primera vez en GitHub Actions el **2026-09-04**, sobre el commit
`30bb668`, y **los tres jobs pasaron**.

Eso cierra lo único que no se podía comprobar en el entorno de desarrollo: el job `imagen`
construyó la imagen, arrancó el contenedor y **su propio HEALTHCHECK lo declaró sano**. Con
ello quedan verificados de una vez el `Dockerfile`, el entrypoint, gunicorn, las settings de
producción y la sonda — incluidas las correcciones DEC-40 y DEC-41, sin las cuales ese paso
habría fallado.

El entorno de desarrollo sigue sin motor de Docker (Docker Desktop necesita WSL, que no está
instalado y no se puede instalar sin privilegios de administrador), así que **el build se
verifica en CI, no en local**. Lo que sí se comprueba sin daemon está en
[`DOCKER.md`](DOCKER.md).
