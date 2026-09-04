# Docker

Dos ficheros de compose y una sola imagen.

| Fichero | Para qué |
|---|---|
| `docker-compose.yml` | Desarrollo: `web`, `db`, `redis`, `worker`, `beat`, con el código montado |
| `docker-compose.prod.yml` | Producción: `web`, `worker`, `beat`, `redis`. Imagen inmutable |

## La imagen

`Dockerfile`, multi-stage sobre `python:3.12-slim` (DEC-13).

- **Dos etapas.** `build-essential` y `libpq-dev` se quedan en la etapa de
  compilación; a la final sólo viaja el virtualenv ya construido y `libpq5`.
- **Usuario no root** (`unicare`), creado en la imagen.
- **Sin secretos.** Ni uno. Todo llega por entorno.
- **Un entrypoint, cuatro roles**: `web`, `worker`, `beat` y `migrate`.
- **Sonda de salud propia**: `scripts/healthcheck.py`.

```bash
docker build -t unicare:latest .
```

### Los roles

```bash
docker run --rm --env-file .env.production unicare:latest web
docker run --rm --env-file .env.production unicare:latest worker
docker run --rm --env-file .env.production unicare:latest beat
docker run --rm --env-file .env.production unicare:latest migrate
```

Cualquier otro argumento se ejecuta tal cual, así que
`... unicare:latest python manage.py shell` funciona.

**Las migraciones no se ejecutan solas.** Es un paso explícito y auditable del
despliegue: dos réplicas arrancando a la vez migrarían en paralelo, y una
migración que falla a mitad de un arranque automático deja el sistema en un
estado que nadie ha decidido.

### La sonda de salud

Mide **liveness**, no readiness: si PostgreSQL se cae, el contenedor no está
roto y reiniciarlo no arregla nada. Sacar la instancia del balanceador es tarea
de `/api/v1/health/ready/`, y para eso está `HEALTHCHECK_PATH`.

No es `curl` por dos razones (DEC-42):

- era el único motivo para instalar un paquete de sistema extra en la imagen;
- **`curl -f` no falla ante un 3xx.** Con `SECURE_SSL_REDIRECT` activo, una
  sonda mal planteada recibe un 301 hacia https y lo cuenta como éxito, sin que
  la petición haya llegado nunca a la vista. Aparentar salud es peor que fallar.

Dos cosas tuvieron que arreglarse para que la sonda funcione de verdad, y las
dos aparecieron **ejecutando la aplicación**, no leyendo el código:

| Síntoma | Causa | Arreglo |
|---|---|---|
| 400 a toda sonda local | `Host: localhost` no está en `ALLOWED_HOSTS` | DEC-40 |
| 301 en lugar de la respuesta | redirect a HTTPS antes de la vista | DEC-41 |

Sin lo primero, el contenedor quedaba *unhealthy* para siempre estando
perfectamente sano, y el orquestador lo reiniciaría en bucle.

## El stack de producción

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

`--env-file` **no es opcional**: `env_file:` alimenta el entorno de los
contenedores, pero la interpolación de `${...}` dentro del YAML es otra cosa y,
sin ese argumento, sale del `.env` del directorio — el de desarrollo.

```bash
cp .env.example .env.production   # y ajustar los valores
```

Diferencias con el compose de desarrollo, y el porqué de cada una:

| | Desarrollo | Producción |
|---|---|---|
| Código | montado (`.:/app`) | dentro de la imagen |
| Settings | `development` | `production` |
| Puertos | `db`, `redis` y `web` publicados | sólo `web`, y en `127.0.0.1` |
| Reinicio | manual | `unless-stopped` |
| Logs | sin límite | `max-size: 10m`, 3 ficheros |
| PostgreSQL | servicio `db` | externo (`DATABASE_URL`) |

**El código no se monta**: lo que corre es exactamente lo que se construyó y se
probó. Un bind mount haría que el contenedor ejecutase lo que haya en el disco
del servidor.

**`web` publica sólo en el loopback del host.** Gunicorn no habla TLS: delante
va un proxy inverso que termina HTTPS y reenvía con `X-Forwarded-Proto`, que es
lo que `SECURE_PROXY_SSL_HEADER` espera. Publicar en `0.0.0.0` expondría
gunicorn en claro.

**Los logs están acotados.** Sin `max-size`, un contenedor de larga vida llena
el disco del host; es una de las formas más tontas de tirar un servicio.

### PostgreSQL

Externo por defecto (DEC-45): en producción la base necesita copias de
seguridad, actualizaciones y persistencia que no deberían depender del ciclo de
vida de este compose.

Para un despliegue en una sola máquina hay un servicio `db` bajo perfil:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml --profile db-local up -d
```

Hay que apuntar además `DATABASE_URL` a ese servicio (`@db:5432`).

### Migrar

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm web migrate
```

### `beat` y su volumen

`beat` escribe en un fichero la última ejecución de cada tarea. Va a un volumen
(`CELERY_BEAT_SCHEDULE_FILENAME`) porque si se pierde en cada reinicio, beat
vuelve a disparar el despacho de recordatorios nada más arrancar.

## Privacidad en los logs

El formato del log de acceso **omite la query string** (DEC-44). El de gunicorn
por defecto registra la línea de petición completa, así que un
`?search=Juan+Perez` de una búsqueda de pacientes acabaría escrito en el log de
cada petición. Se registra la ruta, que es lo que sirve para operar.

Se puede sustituir con `GUNICORN_ACCESS_LOG_FORMAT`, pero conviene mantener la
propiedad.

## Estáticos

En producción la API responde **sólo JSON** (DEC-43), así que no hay estáticos
que servir y `collectstatic` está **desactivado** al arrancar. `COLLECT_STATIC=1`
lo reactiva si se vuelve a habilitar el navegador de DRF.

## Qué está verificado y qué no

**El engine de Docker no está disponible en el entorno de desarrollo de este
proyecto** (Docker Desktop necesita WSL, y WSL no está instalado ni se puede
instalar sin privilegios de administrador). Así que:

| | Estado |
|---|---|
| Reparto de roles del entrypoint | **Ejecutado** con `bash` y binarios de mentira |
| Sonda de salud (200, 503, redirect, puerto cerrado) | **Ejecutada** contra un servidor HTTP real |
| Settings de producción ante una sonda local | **Ejecutadas**: llamada WSGI real en otro proceso |
| Formato del log de acceso | **Ejecutado** con el formateador de gunicorn (en CI; en Windows no se importa) |
| `docker-compose.prod.yml` | **Validado** con `docker compose config`, que no necesita daemon |
| Usuario no root, multi-stage, sin secretos, `.dockerignore` | Comprobado leyendo los ficheros |
| **El build de la imagen** | **Nunca se ha ejecutado aquí** |
| **El contenedor arrancando de verdad** | **Nunca se ha ejecutado aquí** |

Las dos últimas se cubren en CI: el job `imagen` construye la imagen, la
arranca y espera a que su **propio HEALTHCHECK** la declare sana — lo que
ejercita gunicorn, el entrypoint, las settings de producción y la sonda a la
vez. Ese job no se ha ejecutado todavía porque el proyecto aún no es un
repositorio git. Ver [`CI.md`](CI.md).

Los tests están en `tests/test_docker.py`. El procedimiento de puesta en
producción está en [`DEPLOYMENT.md`](DEPLOYMENT.md).
