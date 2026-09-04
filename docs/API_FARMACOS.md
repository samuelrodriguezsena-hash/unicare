# API de fármacos

Consulta en tiempo real del servicio externo de fármacos, expuesta a través del backend.
**El frontend nunca llama al servicio externo**: siempre pasa por este endpoint.

```
Frontend → GET /api/v1/farmacos/ → DRF → FarmacosService → FarmacosAPIClient → API externa
```

No hay catálogo local de medicamentos, ni caché, ni persistencia, ni tareas Celery para esta
funcionalidad: cada petición consulta el servicio externo.

---

## Endpoint

```
GET /api/v1/farmacos/
```

Requiere autenticación JWT, como el resto de la API:

```
Authorization: Bearer <access_token>
```

El JWT del usuario **no** se reenvía al servicio externo. El backend construye su propia
petición, sin credenciales del usuario.

## Filtros

Los cinco filtros son opcionales y combinables. Coincidencia **exacta y sensible a
mayúsculas**, tal como los define el servicio externo — los valores no se normalizan.

| Filtro | Ejemplo |
|---|---|
| `Nombre_Medicamento` | `Sertralina` |
| `Dosis_Comun` | `850 mg` |
| `Compuesto_Principal` | `Paracetamol` |
| `Patologia_Comun` | `Diabetes Tipo 2` |
| `Familia_Farmaco` | `Estatinas` |

Cualquier otro query parameter se rechaza con **400**, y en ese caso no se llega a consultar el
servicio externo. Un filtro presente pero vacío (`?Nombre_Medicamento=`) equivale a no enviarlo.

### Ejemplos

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/farmacos/"
```

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/farmacos/?Nombre_Medicamento=Sertralina"
```

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/farmacos/?Familia_Farmaco=Estatinas"
```

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/farmacos/?Patologia_Comun=Diabetes%20Tipo%202&Dosis_Comun=850%20mg"
```

## Respuesta

`200 OK` con un array. Se mantiene el formato del servicio externo:

```json
[
  {
    "Nombre_Medicamento": "Sertralina",
    "Dosis_Comun": "50 mg",
    "Compuesto_Principal": "Sertralina",
    "Patologia_Comun": "Depresión",
    "Familia_Farmaco": "ISRS"
  }
]
```

Sin resultados — **no es un error**:

```json
[]
```

Se devuelven exactamente esos cinco campos. Si el servicio externo añadiera campos propios,
se descartan y no se filtran hacia el cliente.

## Errores

| Situación | HTTP | `code` |
|---|---|---|
| Query parameter desconocido | `400` | *(error de validación de DRF)* |
| Sin autenticar | `401` | — |
| El servicio externo responde `400` | `400` | `farmacos_api_bad_request` |
| El servicio externo responde `404` | `502` | `farmacos_api_error` |
| El servicio externo responde `5xx` | `502` | `farmacos_api_error` |
| Error de conexión | `502` | `farmacos_api_connection_error` |
| Timeout | `504` | `farmacos_api_timeout` |
| JSON no parseable o estructura inesperada | `502` | `farmacos_api_response_error` |

Formato:

```json
{"detail": "El servicio de farmacos tardo demasiado en responder.", "code": "farmacos_api_timeout"}
```

Dos decisiones que conviene tener presentes:

- **`404` no significa "sin resultados"**. Se trata como problema de configuración o
  integración del servicio externo, y por eso es `502` y no `200 []`.
- **`400` externo se propaga como `400`**, no como `502`. Los filtros los aporta el cliente,
  así que el problema le es atribuible.

Ninguna respuesta de error expone la URL externa, cabeceras, credenciales ni stack traces.

## Sentry

Se reportan los fallos de infraestructura e integración: timeout, error de conexión,
respuestas `5xx`, JSON inválido y estructura inesperada. **No** se reportan los errores
esperables de validación (query parameter desconocido, `400` del servicio externo), para no
generar ruido. Se reutiliza la configuración existente: sin `SENTRY_DSN`, `capture_exception`
es un no-op.

Los filtros no se registran en logs ni en Sentry: pueden contener términos clínicos.

## Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `FARMACOS_API_BASE_URL` | Sí | — | Sólo el host, p. ej. `https://api.ejemplo.com`. La ruta `/v1/farmacos` es parte del contrato del servicio y vive en el código |
| `FARMACOS_API_TIMEOUT` | No | `5` | Segundos. Nunca se usa `timeout=None` |
| `FARMACOS_API_KEY` | No | *(vacío)* | El servicio es hoy público. Si en el futuro exigiera credencial, definirla la envía como `Authorization: Bearer` **sin tocar código** |
| `FARMACOS_CACHE_TTL` | No | `900` | Reservada para la futura caché Redis. **Hoy no se usa** |

En Docker llegan al contenedor por `env_file: [.env]` en `docker-compose.yml`, igual que el
resto de la configuración. No hay ningún valor en el `Dockerfile` ni en código.

> La URL real del servicio todavía no está disponible (`docs/DECISIONS.md`, C-07). El cliente
> está implementado contra el contrato documentado y **se ejercita únicamente con mocks**.

## Diseño

```
apps/medications/
├── views.py                    FarmacoListView — valida filtros y delega
├── serializers.py              FarmacoFilterSerializer, FarmacoSerializer
├── exceptions.py               errores de integración → HTTP
└── services/farmacos_api.py    FarmacosService + FarmacosAPIClient (httpx)
```

- La view no contiene lógica HTTP externa; el cliente HTTP no conoce DRF.
- `httpx.Client` **síncrono**, coherente con el resto del proyecto (WSGI + gunicorn),
  compartido entre peticiones para reutilizar conexiones, y reconstruido automáticamente si
  cambia la configuración.
- Los query parameters los codifica `httpx` vía `params=`; nunca se concatena la query string.
- La respuesta externa se valida con un `Serializer` de DRF. Una respuesta inválida es un error
  de integración, **nunca** un resultado válido.
- `FarmacosService.list_farmacos()` es el único punto de entrada. Caché Redis, sincronización
  Celery o persistencia en PostgreSQL se insertan ahí **sin tocar la view**.

## Tests

`tests/test_farmacos_api.py`. Ninguno sale a Internet: `respx` intercepta el transporte de
`httpx`, y una ruta sin mockear falla en lugar de hacer la petición real. Tampoco necesitan
PostgreSQL.

```bash
python -m pytest tests/test_farmacos_api.py -v
```
