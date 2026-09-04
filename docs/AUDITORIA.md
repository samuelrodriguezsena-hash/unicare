# Auditoría

Registro de quién cambió qué, cuándo y cómo, sobre `AUDIT_LOG` **sin alterar su estructura del
DER**: no se ha añadido ninguna columna.

## Qué se registra

La documentación normativa exige poder conocer ocho cosas. Todas salen de las columnas que el
DER ya define:

| Requisito | De dónde sale |
|---|---|
| Usuario responsable | `user_id` |
| Entidad afectada | `entity_type` (nombre físico de la tabla, p. ej. `patient`) |
| ID de entidad | `entity_id` |
| Operación realizada | `action` (`CREATE` / `UPDATE` / `DELETE`) |
| Valores anteriores | `old_values` (jsonb) |
| Valores nuevos | `new_values` (jsonb) |
| Cambios realizados | **derivado** del diff entre ambos — el DER no define columna `changes` (D-03) |
| Fecha/hora | `created_at` |

Se auditan las **13 entidades de dominio**. `AUDIT_LOG` no se audita a sí mismo: sería recursión
infinita.

## Cómo funciona

```
petición HTTP
    │  CurrentUserMiddleware  →  guarda el request en un ContextVar
    ▼
vista / servicio
    │  .save() / .delete()
    ▼
signals (pre_save → post_save / post_delete)
    │  capturan el estado previo y sellan created_by / updated_by
    ▼
AuditService  →  AUDIT_LOG
```

Se combinan las tres vías que la documentación admite: el **middleware** aporta el usuario, las
**signals** garantizan que ninguna operación crítica se escape (también las que no pasan por un
servicio), y el **servicio** centraliza la escritura.

Detalle no obvio: el middleware guarda el `request`, **no** `request.user`. Con JWT, en el
momento en que corre el middleware el usuario todavía es anónimo — DRF autentica dentro de la
vista y sólo entonces reasigna `request.user`. Guardar el usuario ahí registraría siempre
"anónimo".

## Usuario responsable

`AUDIT_LOG.user_id` es `NOT NULL` en el DER, pero las tareas Celery y los comandos no tienen
usuario autenticado. En vez de relajar la nulabilidad del contrato (C-04):

1. el usuario de la petición HTTP en curso, si lo hay;
2. en su defecto, el usuario técnico **`system`**, creado por `core.0002_system_user` con
   contraseña inutilizable — no puede autenticarse. Configurable con `SYSTEM_USERNAME`.

Para propagar el usuario real a una tarea asíncrona:

```python
from apps.core.context import acting_as

with acting_as(usuario):
    servicio.procesar()
```

## Decisiones

- **En un `UPDATE` se guardan sólo las columnas que cambiaron**, en ambos lados. El DER no
  obliga a guardar la instantánea completa, y limitarlo al cambio hace que `AUDIT_LOG` responda
  directamente a "qué se modificó" sin inflar el jsonb en cada guardado. En `CREATE` y `DELETE`
  sí se guarda el estado completo.
- **Un `save()` que no cambia nada no genera entrada.** No es una operación auditable.
- **Las claves de `old_values`/`new_values` son nombres físicos de columna**, no atributos
  Python: la auditoría habla el idioma del DER.
- **`password` y `last_login` nunca se auditan.** Guardar un hash en jsonb sería filtrarlo.
- **Un fallo de auditoría no tumba la operación de negocio.** Se registra y se reporta a
  Sentry, pero no se propaga: perder una entrada de auditoría es malo; perder el dato clínico,
  peor.
- **`created_by` / `updated_by` se rellenan solos** en las 11 tablas a las que el DER les da esos
  campos, sin pisar un valor fijado explícitamente por el código.

## Endpoints

Todos requieren JWT y son de **sólo lectura**: la auditoría no se puede crear ni modificar por
API.

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/api/v1/audit-logs/` | Listado paginado, más recientes primero |
| GET | `/api/v1/audit-logs/{id}/` | Detalle |
| GET | `/api/v1/audit-logs/export/` | Exportación CSV en streaming |

Filtros comunes a listado y exportación: `entity_type`, `entity_id`, `user`, `action`,
`created_at_after`, `created_at_before`.

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/audit-logs/?entity_type=patient&entity_id=42"
```

```bash
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8000/api/v1/audit-logs/export/?action=DELETE&created_at_after=2026-01-01T00:00:00Z" -o audit.csv
```

Ejemplo de respuesta:

```json
{
  "audit_id": 128,
  "user": 3,
  "username": "dra.rojas",
  "entity_type": "patient",
  "entity_id": 42,
  "action": "UPDATE",
  "changes": ["last_name", "updated_at"],
  "old_values": {"last_name": "Gomez", "updated_at": "2026-08-31T10:00:00+00:00"},
  "new_values": {"last_name": "Gomez Ruiz", "updated_at": "2026-08-31T10:04:12+00:00"},
  "created_at": "2026-08-31T10:04:12.331Z"
}
```

El **CSV de exportación no incluye valores**, sólo los nombres de las columnas modificadas: un
export es un archivo que circula, y no debe difundir contenido clínico.

## Rendimiento

- El listado usa `select_related("user")`: 2 consultas totales, sin N+1 (verificado con
  `django_assert_num_queries`).
- La exportación va en streaming con `iterator(chunk_size=500)`: no carga la tabla en memoria.
- Cada guardado audiado cuesta una lectura del estado previo más la inserción. La resolución
  del usuario **no** cuesta consulta en peticiones HTTP; sólo en Celery y comandos.

## Tests

`tests/test_audit.py` (comportamiento) y `tests/test_audit_api.py` (API). Requieren PostgreSQL
porque la auditoría escribe `jsonb` y se verifica leyendo lo que quedó realmente guardado; se
saltan solos si no hay base.
