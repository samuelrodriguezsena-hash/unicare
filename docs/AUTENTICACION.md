# Autenticación y permisos

JWT sobre `djangorestframework-simplejwt`, con el modelo `USER` del DER.

## Endpoints

| Método | Ruta | Público | Descripción |
|---|---|---|---|
| POST | `/api/v1/auth/token/` | Sí | Obtener par access/refresh |
| POST | `/api/v1/auth/token/refresh/` | Sí | Renovar el access |
| POST | `/api/v1/auth/token/verify/` | Sí | Verificar un token |

Junto a `/health/` y `/health/ready/`, son **los únicos endpoints públicos**. Sin ellos no
habría forma de obtener el primer token, y las sondas las consulta el orquestador, que no tiene
credenciales.

```bash
curl -X POST -H "Content-Type: application/json" \
  -d '{"username":"dra.rojas","password":"..."}' \
  http://localhost:8000/api/v1/auth/token/
```

```json
{"access": "eyJhbGciOi...", "refresh": "eyJhbGciOi..."}
```

```bash
curl -H "Authorization: Bearer $ACCESS" http://localhost:8000/api/v1/patients/
```

## Compatibilidad con el DER — C-02

Esta fase es donde se comprueba de verdad la decisión C-02. `core.User`:

- hereda de `AbstractBaseUser` **sin** `PermissionsMixin`;
- su PK es **`user_id`**, no `id`;
- sólo añade al DER dos columnas: `password` y `last_login`.

Que JWT funcione con eso no era evidente. Se resuelve con `USER_ID_FIELD: "user_id"` en
`SIMPLE_JWT` — simplejwt asume `id` por defecto. Hay tests que verifican que el token lleva la
PK correcta y que **no existen** las tablas `user_groups` ni `user_user_permissions`.

## Sin rotación ni lista negra — DEC-35

`ROTATE_REFRESH_TOKENS = False` y `BLACKLIST_AFTER_ROTATION = False`.

Activar la rotación hace que simplejwt llame a `refresh.outstand()`, que escribe en
`OutstandingToken` — un modelo de la app `token_blacklist`, que **añade dos tablas que el DER no
contempla**. Sin esa app instalada, activar la rotación hace que refrescar responda **500**.

Consecuencias, asumidas y documentadas:

- Un refresh token sigue siendo válido hasta que caduca y **no se puede revocar**: el "logout"
  es del lado del cliente (descartar los tokens).
- La mitigación es la vida corta de los tokens, sobre todo la del access.

| Variable | Default |
|---|---|
| `JWT_ACCESS_TOKEN_LIFETIME` | 15 minutos |
| `JWT_REFRESH_TOKEN_LIFETIME` | 1440 minutos (24 h) |

La clave de firma es `DJANGO_SECRET_KEY`; no está hardcodeada en ningún sitio.

## Política de permisos — C-03

**No hay roles.** El DER no define `role`, `is_staff` ni relación con grupos en `USER`. La única
dimensión de autorización que el contrato contempla es `is_active`.

Regla vigente: **usuario autenticado y activo** para toda operación. La auditoría es además de
sólo lectura: no se puede falsificar un registro por API.

Toda la política vive en `apps/core/permissions.py`, separada de la lógica de negocio como exige
la documentación. Añadir roles más adelante es un cambio localizado en ese módulo: las vistas no
cambian.

| Clase | Uso |
|---|---|
| `IsAuthenticatedAndActive` | Todos los endpoints de dominio |
| `CanReadAuditLog` | Auditoría (además, sólo lectura) |
| `ReadOnly` | Combinable |

## Respuestas

| Situación | HTTP |
|---|---|
| Sin cabecera `Authorization` | `401` |
| Token inválido, caducado o firmado con otra clave | `401` |
| Refresh token usado como access | `401` |
| Usuario desactivado después de emitir el token | `401` |
| Autenticado pero inactivo | `403` |

El usuario técnico `system` **no puede autenticarse**: se crea con contraseña inutilizable
(C-04).

## Garantía de cobertura

`tests/test_permissions_coverage.py` recorre el **URLconf entero** y verifica que todo endpoint
no declarado público rechaza a un anónimo, en `GET`, `POST`, `PATCH` y `DELETE`.

Un endpoint nuevo sin permisos hace fallar ese test aunque nadie escriba un test específico para
él. Está comprobado que detecta el caso: al desproteger deliberadamente `pathologies/`, falla
nombrando la ruta y el método.

## Tests

`tests/test_jwt_auth.py` (29) y `tests/test_permissions_coverage.py` (37). Requieren PostgreSQL.

> El resto de la suite usa `force_authenticate`, que **salta la autenticación por completo**.
> `test_jwt_auth.py` es el único módulo que ejercita el camino real: obtener el token, firmarlo,
> mandarlo en la cabecera y validarlo. Incluye el circuito completo
> JWT → middleware → `AUDIT_LOG`.
