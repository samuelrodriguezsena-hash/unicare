# API de planes de tratamiento

Planes de tratamiento y los medicamentos asociados. **No hay catálogo local de fármacos**: la
API externa es la única fuente farmacológica, y el DER referencia el medicamento por
`external_medication_id` más dos snapshots desnormalizados.

Todos los endpoints requieren JWT y usuario activo.

## Endpoints

| Método | Ruta | Descripción |
|---|---|---|
| GET / POST | `/api/v1/treatment-plans/` | Listado filtrable / alta (atómica) |
| GET / PATCH | `/api/v1/treatment-plans/{id}/` | Detalle / modificación |
| GET / POST | `/api/v1/treatment-plans/{id}/medications/` | Medicamentos del plan |
| PATCH / DELETE | `/api/v1/treatment-plan-medications/{id}/` | Posología / quitar |
| GET | `/api/v1/treatment-plan-medications/{id}/alternatives/` | Alternativas de la misma familia |
| GET | `/api/v1/farmacos/` | Autocompletado — ver [`API_FARMACOS.md`](API_FARMACOS.md) |

Filtros del listado: `patient`, `pathology`, `status`, `ordering`.

## Alta de un plan

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"patient":42,"pathology":3,"name":"Manejo de dislipidemia","start_date":"2026-09-01","status":"ACTIVE"}' \
  http://localhost:8000/api/v1/treatment-plans/
```

`pathology` es opcional (A-05: el DER la declara FK nullable). `status` admite `DRAFT`,
`ACTIVE`, `COMPLETED`, `CANCELLED` (DEC-03).

Se pueden incluir medicamentos en el alta, y entonces **la operación es atómica**: si falla la
asociación de cualquiera, no se crea el plan. Un plan a medio poblar sería clínicamente
engañoso.

```json
{
  "patient": 42, "name": "Manejo de dislipidemia", "start_date": "2026-09-01",
  "medications": [{"external_medication_id": "Atorvastatina", "dose": "20 mg"}]
}
```

## Asociar un medicamento

```bash
curl -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"external_medication_id":"Atorvastatina","dose":"20 mg","frequency":"cada 24 h"}' \
  http://localhost:8000/api/v1/treatment-plans/7/medications/
```

Qué ocurre por dentro:

1. Se consulta la API externa por `Nombre_Medicamento` (coincidencia exacta, sensible a
   mayúsculas). Si no existe → `400`.
2. Se guardan `medication_name_snapshot` y `medication_family_snapshot` con lo que la fuente
   decía **en ese momento**.
3. Se ejecuta la validación cruzada.

> **`external_medication_id`**: la API externa no publica ningún campo identificador — sus cinco
> campos son atributos, no claves. Se interpreta como el `Nombre_Medicamento` publicado por esa
> API, el único identificador natural disponible (DEC-20).

Los snapshots, `validation_status` y `warning_flag` **no son escribibles**: los fija el
servidor. Si el cliente pudiera enviarlos, podría declarar como validado algo que no lo está.

## Validación cruzada

Compara la `Patologia_Comun` del fármaco con las patologías registradas del paciente y con la
del plan.

**No es una validación clínica.** Es una comparación literal de nombres, que ignora mayúsculas
y espacios; ni interpreta, ni decide, ni sustituye el criterio profesional.

| Resultado | `validation_status` | `warning_flag` | HTTP |
|---|---|---|---|
| Coincide | `VALIDATED` | `false` | `201` |
| No coincide | `WARNING` | `true` | **`201`** |
| Nada que comparar | `PENDING` | `false` | `201` |

**Una discrepancia advierte, nunca bloquea** — es explícito en la documentación normativa. La
advertencia viaja en un objeto `validation` **separado del recurso**, para que no se confunda
con un atributo clínico del medicamento:

```json
{
  "treatment_plan_medication_id": 15,
  "medication_name_snapshot": "Atorvastatina",
  "validation_status": "WARNING",
  "warning_flag": true,
  "validation": {
    "status": "WARNING",
    "warning": true,
    "message": "ADVERTENCIA: la patologia habitual de este medicamento (Diabetes Tipo 2) no coincide con ninguna patologia registrada del paciente. Es una comparacion automatica de nombres, no una validacion clinica: requiere revision por un profesional."
  }
}
```

## Alternativas farmacológicas

```bash
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/api/v1/treatment-plan-medications/15/alternatives/
```

Sigue el flujo que exige la documentación: obtiene el fármaco de la API externa, lee su
`Familia_Farmaco`, vuelve a buscar por esa familia y excluye el medicamento actual. Si la
familia no consta, devuelve lista vacía: **no se inventa información farmacológica local**.

```json
{
  "external_medication_id": "Atorvastatina",
  "family": "Estatinas",
  "alternatives": [{"Nombre_Medicamento": "Simvastatina", "Dosis_Comun": "40 mg", "...": "..."}]
}
```

## Modificar y quitar

`PATCH /treatment-plan-medications/{id}/` sólo admite posología: `dose`, `frequency`,
`duration`, `route`, `instructions`. **`external_medication_id` no es modificable** —
cambiarlo invalidaría los snapshots y la validación ya registrados (DEC-22). Para cambiar de
fármaco se quita y se asocia otro.

## Errores

| Situación | HTTP | `code` |
|---|---|---|
| Datos inválidos, fecha de fin anterior al inicio, estado fuera del enum | `400` | — |
| El medicamento no existe en la fuente externa | `400` | `medication_not_found` |
| Sin autenticar / usuario inactivo | `401` / `403` | — |
| Plan o medicamento inexistente | `404` | — |
| `DELETE` de un plan | `405` | — |
| La API externa falla o no responde | `502` / `504` | ver [`API_FARMACOS.md`](API_FARMACOS.md) |

**Si la API externa no responde, el medicamento no se guarda** (DEC-21). Sin ella no hay
snapshot ni validación cruzada, y persistir información clínica sin validar sería peor que
fallar. Es distinto de una discrepancia, que sí se acepta con advertencia.

## Rendimiento

El listado usa `select_related("patient", "pathology")` y `prefetch_related("medications")`:
4 consultas independientemente del número de planes, verificado con
`django_assert_max_num_queries`.

## Tests

`tests/test_treatment_plans.py` (36 tests). Ninguna llamada real a la API externa: `respx`
intercepta el transporte de httpx. Requiere PostgreSQL.

> `POST /api/v1/treatment-suggestions/` (sugerencia de tratamiento con IA) llega en la
> **FASE 9**.
