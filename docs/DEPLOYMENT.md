# Despliegue

Guía de puesta en producción de UniCare. La mecánica del contenedor está en
[`DOCKER.md`](DOCKER.md); aquí está el procedimiento completo, en orden.

**Lo que sigue se ha ensayado contra un PostgreSQL real** — migraciones,
creación del usuario administrativo, health checks, autenticación y marcha
atrás de migraciones. Lo que **no** se ha podido ejecutar es el build de la
imagen: ver [§14](#14-qué-está-ensayado-y-qué-no).

---

## 1. Requisitos

| | Versión | Nota |
|---|---|---|
| Docker Engine | 24+ | Con `docker compose` v2 |
| PostgreSQL | 16 | Gestionado o propio. **Nunca SQLite** |
| Redis | 7 | Broker de Celery y caché |
| Un dominio con DNS | — | Y un proxy inverso que termine TLS |

Recursos mínimos razonables para un despliegue pequeño: 2 vCPU y 2 GB de RAM
para la aplicación (tres procesos: `web`, `worker`, `beat`), más lo que pida la
base de datos.

El proyecto es **agnóstico de proveedor**: no hay ningún SDK ni configuración de
AWS, GCP, Azure, Render, Railway o Fly. Todo el acoplamiento a infraestructura
pasa por `DATABASE_URL` y `REDIS_URL`.

---

## 2. Variables de entorno

```bash
cp .env.example .env.production
```

`.env.example` es el inventario completo y está comentado. **No contiene ningún
valor real**, y `.env.production` no se versiona (`.gitignore` ignora `.env.*`).

Obligatorias, sin valor por defecto — el proceso **no arranca** sin ellas:

| Variable | Nota |
|---|---|
| `DJANGO_SECRET_KEY` | Ver más abajo |
| `DJANGO_ALLOWED_HOSTS` | Dominios servidos, separados por comas. Vacía **aborta el arranque** (DEC-39) |
| `DATABASE_URL` | `postgres://usuario:password@host:5432/basededatos` |
| `REDIS_URL` | `redis://host:6379/0` |
| `FARMACOS_API_BASE_URL` | Sin valor por defecto: la URL documentada es un placeholder (C-07) |

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

**La clave tiene que superar los 50 caracteres.** Por debajo, Django emite el
aviso `security.W009` y `check --deploy --fail-level WARNING` falla — que es
justo lo que se quiere.

Opcionales pero recomendadas en producción: `SENTRY_DSN` ([§9](#9-sentry)),
`GEMINI_API_KEY` (sin ella los endpoints de IA responden 503 pero **el resto del
sistema funciona**), `CORS_ALLOWED_ORIGINS` si hay frontend en otro dominio.

> **Cero secretos en el repositorio.** Ninguna clave, contraseña o DSN se
> escribe en el código, ni en el `Dockerfile`, ni en los compose. Todo llega por
> entorno, y hay tests que fallan si aparece un valor hardcodeado.

---

## 3. Crear PostgreSQL

Con una base gestionada, basta con crearla y apuntar `DATABASE_URL`. Si se
crea a mano:

```bash
createuser --pwprompt unicare
createdb --owner=unicare unicare
```

```
DATABASE_URL=postgres://unicare:LA_PASSWORD@el-host:5432/unicare
```

El esquema lo crean las migraciones ([§7](#7-migraciones)); no hay que ejecutar
ningún SQL a mano.

Dos cosas del esquema conviene saberlas:

- La tabla de usuarios se llama `"user"`, que es **palabra reservada** en
  PostgreSQL (DEC-14). Django la entrecomilla siempre; cualquier SQL escrito a
  mano contra ella tiene que hacerlo también.
- Hay columnas `jsonb` e índices únicos parciales. Es PostgreSQL 16 o
  equivalente, no un motor cualquiera.

**Copias de seguridad**: son responsabilidad del despliegue, no del proyecto.
Si se usa el servicio `db` del perfil `db-local` (DEC-45), los datos viven en el
volumen `postgres_data` y hay que respaldarlos con `pg_dump`.

---

## 4. Configurar Redis

```
REDIS_URL=redis://el-host:6379/0
```

Redis es **broker de Celery y caché**. Conviene `appendonly yes` (así lo hace el
compose): una cola de recordatorios pendientes sobrevive a un reinicio.

Qué pasa exactamente si Redis se cae — **comprobado**:

| | Con Redis caído |
|---|---|
| API (pacientes, citas, planes, auditoría, login) | **Sigue funcionando** |
| `/api/v1/health/` (liveness) | 200 |
| `/api/v1/health/ready/` (readiness) | **503**, con `"cache": false` |
| Recordatorios (Celery) | No se procesan hasta que vuelva |

Es decir: una caída de Redis saca la instancia del balanceador pero no rompe la
API. Si Redis está en otra máquina, **no lo expongas a internet**.

---

## 5. Construir la imagen

```bash
docker build -t unicare:1.0.0 .
```

Etiqueta con una versión, no con `latest`: sin una etiqueta concreta a la que
volver, [el rollback](#13-rollback) no existe.

```bash
docker tag unicare:1.0.0 registro.example.com/unicare:1.0.0
docker push registro.example.com/unicare:1.0.0
```

En `.env.production`, `UNICARE_IMAGE` selecciona qué imagen despliega el compose.

---

## 6. Desplegar

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

`--env-file` **no es opcional**: sin él, compose interpola `${...}` desde el
`.env` del directorio, que es el de desarrollo.

Levanta cuatro contenedores: `web` (gunicorn), `worker` y `beat` (Celery) y
`redis`. PostgreSQL es externo salvo que se use `--profile db-local`.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml ps
docker compose --env-file .env.production -f docker-compose.prod.yml logs -f web
```

`web` publica **sólo en `127.0.0.1`**: la puerta de entrada es el proxy inverso
([§11](#11-ssl)).

---

## 7. Migraciones

**No se ejecutan solas.** Es deliberado: dos réplicas arrancando a la vez
migrarían en paralelo, y una migración que falla a mitad de un arranque
automático deja el sistema en un estado que nadie ha decidido.

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm web migrate
```

La primera vez crea las **14 tablas del DER** y, con ellas, el usuario técnico
`system` (migración `core.0002_system_user`): `AUDIT_LOG.user_id` es `NOT NULL` y
las tareas automáticas no tienen usuario autenticado, así que se les atribuye a
él (C-04). No puede autenticarse — tiene contraseña inutilizable.

Para ver qué hay aplicado:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm web python manage.py showmigrations
```

---

## 8. Usuario administrativo

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
  -e DJANGO_SUPERUSER_USERNAME=admin \
  -e DJANGO_SUPERUSER_PASSWORD='LA_PASSWORD' \
  web python manage.py createsuperuser --noinput
```

Dos advertencias sobre esto:

- **No existen roles ni privilegios distintos.** El DER no define `is_staff` ni
  `is_superuser`, y el proyecto no usa `PermissionsMixin` (C-02, C-03). Aquí
  `createsuperuser` es un alias de `create_user`: crea un usuario normal. El
  nombre lo pone Django, no el dominio.
- **No pide email**, porque `REQUIRED_FIELDS` está vacío. Si el usuario necesita
  email, se le asigna después por la API.

La contraseña en la línea de comandos queda en el historial del shell. Mejor
pasarla por un fichero de entorno o crear el usuario de forma interactiva
(sin `--noinput`).

Comprobación:

```bash
curl -X POST https://TU-DOMINIO/api/v1/auth/token/ \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"LA_PASSWORD"}'
```

Debe devolver `access` y `refresh`. Ver [`AUTENTICACION.md`](AUTENTICACION.md).

---

## 9. Sentry

```
SENTRY_DSN=https://...@....ingest.sentry.io/...
SENTRY_ENVIRONMENT=production
SENTRY_TRACES_SAMPLE_RATE=0.1
SENTRY_RELEASE=1.0.0
```

**Vacío o ausente = Sentry desactivado**, y el sistema funciona igual.

Sentry es un tercero y este sistema maneja información clínica, así que el
saneado es agresivo por defecto: no se envía el cuerpo de la petición
(`max_request_body_size="never"`, DEC-36), ni cabeceras, ni cookies, ni query
string; del usuario sólo va su ID. `SENTRY_RELEASE` con la misma etiqueta que la
imagen hace que los errores se puedan atribuir a una versión concreta.

Detalle completo en [`OBSERVABILIDAD.md`](OBSERVABILIDAD.md).

---

## 10. Dominio

1. Un registro `A`/`AAAA` apuntando al servidor.
2. El dominio **en `DJANGO_ALLOWED_HOSTS`**, o Django responde 400 a todo.
3. Si hay frontend en otro origen, ese origen en `CORS_ALLOWED_ORIGINS` y en
   `CSRF_TRUSTED_ORIGINS`.

```
DJANGO_ALLOWED_HOSTS=unicare.example.com
CORS_ALLOWED_ORIGINS=https://app.example.com
CSRF_TRUSTED_ORIGINS=https://app.example.com
```

`localhost` y `127.0.0.1` se añaden solos en producción, para que las sondas
locales no reciban un 400 (DEC-40). No hay que ponerlos.

---

## 11. SSL

**Gunicorn no habla TLS.** Delante va un proxy inverso que termina HTTPS y
reenvía `X-Forwarded-Proto`, que es lo que espera `SECURE_PROXY_SSL_HEADER`. Sin
esa cabecera, Django cree que la petición es HTTP y la redirige en bucle.

Ejemplo mínimo con nginx (no forma parte del proyecto):

```nginx
server {
    listen 443 ssl;
    server_name unicare.example.com;

    ssl_certificate     /etc/letsencrypt/live/unicare.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/unicare.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    }
}
```

Certificados con Let's Encrypt (`certbot`) o los que provea la infraestructura.

Lo que activa el propio Django en producción: redirect a HTTPS, HSTS con
`preload` y un año de duración, cookies `Secure`, `X-Frame-Options: DENY` y
`nosniff`. Se verifican en CI con `check --deploy --fail-level WARNING`.

**HSTS con `preload` es difícil de revertir**: los navegadores recuerdan un año.
No lo actives hasta tener el certificado en orden. `DJANGO_SECURE_HSTS_SECONDS`
permite empezar con un valor bajo.

Los dos health checks están **exentos del redirect** (DEC-41), para que una
sonda local reciba la respuesta y no un 301.

---

## 12. Health checks

| Endpoint | Qué mide | Respuestas |
|---|---|---|
| `GET /api/v1/health/` | **Liveness**: el proceso responde. No toca nada | `200 {"status":"ok"}` |
| `GET /api/v1/health/ready/` | **Readiness**: PostgreSQL y Redis | `200 ready` / `503 not-ready` con el detalle |

Ambos son públicos y no devuelven información clínica.

```json
{"status": "not-ready", "checks": {"database": true, "cache": false}}
```

El contenedor trae su propio `HEALTHCHECK`, que usa **liveness**: si PostgreSQL
se cae, el contenedor no está roto y reiniciarlo no arregla nada. Sacar la
instancia del balanceador es tarea de la readiness.

En un balanceador o un orquestador:

- *liveness probe* → `/api/v1/health/`
- *readiness probe* → `/api/v1/health/ready/`

Ninguno depende de Gemini ni de la API de fármacos: la caída de un proveedor
externo no debe sacar el backend del balanceador.

---

## 13. Rollback

**Volver a la imagen anterior** — por eso las etiquetas con versión:

```bash
# En .env.production: UNICARE_IMAGE=registro.example.com/unicare:0.9.0
docker compose --env-file .env.production -f docker-compose.prod.yml up -d
```

**Si la versión nueva traía migraciones**, hay que revertirlas **antes** de
volver atrás, porque la imagen antigua no conoce el esquema nuevo:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml run --rm \
  web python manage.py migrate NOMBRE_DE_LA_APP NUMERO_ANTERIOR
```

Comprobado: revertir y volver a aplicar funciona en los dos sentidos.

Tres avisos:

- **Una migración que borra datos no se deshace.** Revertirla recrea la columna,
  vacía. Antes de un despliegue con migraciones destructivas, `pg_dump`.
- La reversión de `core.0002_system_user` **sólo borra el usuario `system` si no
  dejó rastro en la auditoría**: `AUDIT_LOG.user_id` usa `PROTECT` y perder
  registros de auditoría sería inaceptable.
- Un `docker compose down -v` **borra los volúmenes**, y con ellos Redis y —si se
  usa el perfil `db-local`— la base de datos. Para parar sin destruir nada:
  `down` sin `-v`.

---

## 14. Qué está ensayado y qué no

Contra un PostgreSQL 16 real, con `config.settings.production` cargadas:

| | |
|---|---|
| `check --deploy --fail-level WARNING` | **Ejecutado** — y detectó una clave demasiado corta |
| `migrate` desde una base vacía | **Ejecutado** — 14 tablas y el usuario `system` |
| `createsuperuser --noinput` | **Ejecutado** |
| `POST /api/v1/auth/token/` con ese usuario | **Ejecutado** — devuelve `access` |
| Liveness y readiness | **Ejecutados**, incluido el 503 con Redis caído |
| La API con Redis caído | **Ejecutada** — sigue respondiendo 200 |
| Marcha atrás de migraciones y reaplicación | **Ejecutadas** |
| **Build de la imagen** | **Ejecutado en CI**. En local no: no hay engine de Docker |
| El contenedor arrancando y declarándose sano | **Ejecutado en CI** |
| **El stack de compose levantado** | **No ejecutado**: ni en local ni en CI |
| Un despliegue completo detrás de nginx con TLS | **No ejecutado**: requiere servidor y dominio |

El build y el arranque los cubre el job `imagen` del pipeline, que **se ejecutó por primera
vez el 2026-09-04 y pasó**. Lo que sigue sin ejercitarse en ningún sitio es el stack de compose
completo y un despliegue real detrás de nginx con TLS. Ver [`CI.md`](CI.md) y
[`DOCKER.md`](DOCKER.md).

---

## 15. Problemas frecuentes

**400 en todas las peticiones**
El dominio no está en `DJANGO_ALLOWED_HOSTS`. En los logs aparece
`Invalid HTTP_HOST header`.

**El contenedor arranca y muere en seguida**
Falta una variable obligatoria. `ImproperlyConfigured` dice cuál:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs web
```

**El contenedor queda `unhealthy`**
Comprueba la sonda desde dentro; distingue entre "no arranca" y "no responde":

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml exec web \
  python /app/scripts/healthcheck.py
```

**Bucle de redirects**
El proxy no está mandando `X-Forwarded-Proto: https` ([§11](#11-ssl)).

**`readiness` devuelve 503 con `"database": false`**
`DATABASE_URL` mal, la base no acepta conexiones, o el firewall. La API tampoco
funcionará.

**`readiness` devuelve 503 con `"cache": false`**
Redis. La API sigue funcionando; los recordatorios no.

**No salen recordatorios**
Hacen falta `worker` **y** `beat`, los dos. `beat` planifica y `worker` ejecuta:

```bash
docker compose --env-file .env.production -f docker-compose.prod.yml logs beat worker
```

Con el backend de notificaciones por defecto los avisos **sólo se registran en
el log, no se envían**: integrar un proveedor real consiste en escribir un
backend y apuntar `NOTIFICATION_BACKEND` ahí. Ver
[`RECORDATORIOS.md`](RECORDATORIOS.md).

**Los endpoints de IA devuelven 503**
Falta `GEMINI_API_KEY`. Es una degradación deliberada: el resto del sistema
funciona sin ella, y agendar una cita nunca se bloquea porque la IA no responda
(DEC-26).

**`/api/v1/farmacos/` devuelve 502 o 504**
La API externa no responde o no es la real: la URL documentada es un placeholder
(C-07). Ver [`API_FARMACOS.md`](API_FARMACOS.md).

**Una migración falla a medias**
No se despliega encima. Revisa el error, restaura el `pg_dump` si hizo falta y
vuelve a intentarlo. Las migraciones son un paso explícito precisamente para
poder pararse aquí.
