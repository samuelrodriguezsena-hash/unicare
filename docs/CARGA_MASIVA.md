# Carga masiva de pacientes y patologías

Importación desde CSV y XLSX sobre `IMPORT_BATCH` e `IMPORT_BATCH_ROW`, **sin añadir ninguna
columna al DER**.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| POST | `/api/v1/import-batches/` | Subir archivo (`multipart/form-data`, campo `file`) |
| GET | `/api/v1/import-batches/` | Listado de lotes, filtrable por `status` |
| GET | `/api/v1/import-batches/{id}/` | Estado y contadores |
| GET | `/api/v1/import-batches/{id}/rows/` | Filas, filtrables por `status` |
| GET | `/api/v1/import-batches/{id}/report/` | Reporte CSV |

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" \
  -F "file=@pacientes.csv" http://localhost:8000/api/v1/import-batches/
```

Devuelve `202 Accepted`: el archivo se parsea de forma síncrona (para poder rechazar de
inmediato uno mal formado) y el procesamiento se encola.

## Formato del archivo

| Columna | Obligatoria |
|---|---|
| `identification_number` | **Sí** |
| `first_name` | **Sí** |
| `last_name` | **Sí** |
| `pathology` | **Sí** |
| `date_of_birth`, `phone`, `email`, `address` | No |
| `diagnosis_date`, `is_primary`, `notes` | No |

Las cabeceras se normalizan (espacios, mayúsculas), se descarta el BOM que añade Excel, y las
columnas desconocidas se ignoran en silencio: un archivo exportado de otro sistema suele traer
columnas de más.

Fechas admitidas: `YYYY-MM-DD`, `DD/MM/YYYY`, `DD-MM-YYYY`. En XLSX, las celdas con formato de
fecha se aceptan directamente.

> **DEC-33:** ni el DER ni la documentación funcional definen las columnas del archivo. Este
> contrato mínimo está alineado con lo que `IMPORT_BATCH_ROW` guarda como snapshot.
> **Requiere confirmación.**

Tope de **10 000 filas** por archivo, para que uno enorme no agote la memoria del worker.

## Cómo se procesa

```
Archivo → parseo → filas persistidas (PENDING) → Celery → resultado por fila → reporte
```

Por cada fila:

1. Validar la identificación (`core.validators`, DEC-17).
2. Buscar el paciente por identificación.
3. Crearlo si no existe; si existe, **se reutiliza** y no se sobrescriben sus datos.
4. Crear la patología si no existe en el catálogo.
5. Asociarla, **sin duplicar** una que el paciente ya tenga.

**Una fila inválida no detiene la carga.** Cada fila va en su propia transacción: si falla, se
marca `ERROR` con su motivo y el resto continúa. Y como la transacción es por fila, una fila que
falla a mitad **no deja datos a medias** — si la patología es inválida, el paciente de esa fila
tampoco se crea.

Reimportar el mismo archivo no falla ni duplica: es idempotente.

Si una fila pide `is_primary` y el paciente ya tiene patología principal, la patología **se
asocia igual pero como secundaria**. El DER sólo admite una principal por paciente, y perder la
fila entera por eso sería peor que registrarla sin marcar.

> **DEC-32 — dónde vive el archivo:** el DER sólo define `source_file_name` y
> `source_file_type`; **no hay ninguna columna donde guardar el archivo**. En vez de añadir una,
> el archivo se parsea al subirlo y cada línea se persiste como `IMPORT_BATCH_ROW`, que ya tiene
> exactamente los snapshots necesarios. El archivo no se retiene: **las filas son el estado
> intermedio**, y el procesamiento asíncrono no necesita almacenamiento externo.

## Estados

| `IMPORT_BATCH.status` | Cuándo |
|---|---|
| `PENDING` | Registrado, aún sin procesar |
| `PROCESSING` | En curso |
| `COMPLETED` | Todas las filas correctas |
| `COMPLETED_WITH_ERRORS` | Al menos una fila con error |
| `FAILED` | Fallo global, ajeno a las filas |

`IMPORT_BATCH_ROW.status`: `PENDING` → `SUCCESS` / `ERROR`.

## Reporte

`GET /api/v1/import-batches/{id}/report/` devuelve un CSV en streaming con una línea por fila:
número, identificación, snapshots, estado y **motivo del error**.

Los contadores del lote (`total_rows`, `success_count`, `failure_count`) permiten saber el total
procesado, los éxitos y los errores sin leer el reporte.

Ejemplos de motivo:

```
Formato de fecha incorrecto en 'date_of_birth': no-es-fecha
El numero de identificacion tiene un formato invalido: ...
Faltan datos requeridos: first_name, last_name.
```

> La documentación normativa cita `"ID de paciente no encontrado"` como ejemplo de error. En
> este flujo **no aplica**: un paciente que no existe se crea, no es un error. Se usan mensajes
> que describen lo que realmente falló en vez de reutilizar ese texto donde sería engañoso.

## Errores de la subida

| Situación | HTTP |
|---|---|
| Extensión distinta de `.csv` / `.xlsx` | `400` |
| Faltan columnas obligatorias | `400` |
| Archivo no legible, no UTF-8, vacío o sin filas | `400` |
| Supera el máximo de filas | `400` |
| Sin autenticar / usuario inactivo | `401` / `403` |

Un archivo rechazado **no crea ningún lote**: no hay nada que importar.

## Auditoría

El usuario que lanzó la importación se propaga hasta la tarea Celery con `acting_as`, de modo
que los pacientes y patologías creados se atribuyen **a él** y no al usuario técnico `system`
(C-04). `created_by` queda relleno correctamente. Hay tests que lo verifican.

## Tests

`tests/test_massive_load.py` (66). Requieren PostgreSQL. Cubren CSV y XLSX, paciente existente y
nuevo, patología duplicada, error por fila que no aborta el lote, transaccionalidad por fila,
generación del reporte, límites, y la atribución de auditoría.
