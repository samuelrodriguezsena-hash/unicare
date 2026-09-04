# Recordatorios de citas

Avisos automáticos **48 h y 24 h antes** de cada cita, sobre `APPOINTMENT_REMINDER` y **sin
añadir ninguna columna al DER**.

## Flujo

```
agendar cita ──on_commit──► schedule_reminders_for_appointment
                                    │ crea 2 recordatorios PENDING
                                    ▼
beat (cada 15 min) ──► dispatch_due_reminders
                            │ encola uno por recordatorio vencido
                            ▼
                       send_reminder  ──► NotificationService ──► backend
                            │
                     SENT / FAILED + failure_reason
```

`dispatch_due_reminders` **sólo selecciona y encola**; no envía. Si enviara, un proveedor lento
bloquearía el resto del lote y un fallo obligaría a reintentar recordatorios ya entregados.

## Tareas Celery

| Tarea | Disparo | Qué hace |
|---|---|---|
| `schedule_reminders_for_appointment` | Al agendar | Crea los avisos pendientes |
| `reschedule_reminders_for_appointment` | Al reprogramar | Rehace los pendientes |
| `dispatch_due_reminders` | `beat`, cada 15 min | Encola los vencidos |
| `send_reminder` | Encolada | Envía uno, con reintentos |

Las tareas se encolan con `transaction.on_commit`: si se encolaran de inmediato, el worker
podría leer la cita antes de que la transacción se confirme y no encontrarla.

## Programación

- Offsets configurables con `REMINDER_OFFSETS_HOURS` (por defecto `48,24`).
- **Se omiten los avisos cuyo momento ya pasó**: no tiene sentido programar un aviso de −48 h
  para una cita que es mañana.
- **Idempotente**: no duplica un recordatorio ya programado para el mismo instante. El DER no
  declara `UNIQUE(appointment, scheduled_at)`, así que lo garantiza el servicio.
- **Al reprogramar**, los pendientes se descartan y se rehacen. Los ya enviados **no se tocan**:
  son historia de lo que el paciente recibió.

### Elección de canal (DEC-29)

El DER declara `channel` nullable y no dice cómo elegirlo:

| Contacto del paciente | Canal |
|---|---|
| Tiene email | `EMAIL` |
| Sólo teléfono | `SMS` |
| Ninguno | **No se programan recordatorios** |

Se prefiere email por ser el único canal sin coste por mensaje. Programar un aviso que no se
puede entregar sólo generaría fallos.

## Reintentos — C-05

**El DER no define ningún contador de intentos, y no se le añade.** Los reintentos viven en
Celery: `autoretry_for=(NotificationError,)`, `max_retries=3`, backoff exponencial con jitter.

Sólo en el **último** intento se marca `FAILED` con su `failure_reason`. Marcarlo antes daría
por perdido algo que aún se va a reintentar.

> **Limitación documentada:** no hay trazabilidad persistida del *número* de intentos, sólo la
> que quede en los logs y en Sentry. Lo que sí se persiste es el resultado final: `status`,
> `sent_at`, `failure_reason` — las tres columnas que el DER sí define.

El envío es idempotente: un recordatorio ya `SENT` no se reenvía.

## Notificaciones

El dominio de citas **no conoce ningún proveedor**. Habla con `NotificationService`, que delega
en un backend intercambiable vía `NOTIFICATION_BACKEND`.

Hoy sólo existe `LoggingNotificationBackend`, que registra el envío sin contactar con nadie. Es
deliberado: la documentación pide que la arquitectura **permita** integrar email y SMS después,
y no hay ningún proveedor contratado que se pueda configurar sin inventarlo.

Integrar uno real es escribir una clase con `send(notification)` y apuntar la variable ahí, sin
tocar `appointments`. Hay un test que recorre esa app y falla si aparece `smtplib`, `twilio`,
`sendgrid` o `boto3`.

### Privacidad

- El mensaje **no revela información clínica**: ni el motivo de consulta ni la patología. Un
  recordatorio viaja por un canal no seguro.
- Los logs registran canal y asunto, **nunca** el cuerpo ni el destinatario.

## Configuración

| Variable | Default | Notas |
|---|---|---|
| `REMINDER_OFFSETS_HOURS` | `48,24` | Horas antes de la cita |
| `REMINDER_DISPATCH_MINUTES` | `15` | Cada cuánto revisa `beat` |
| `NOTIFICATION_BACKEND` | `LoggingNotificationBackend` | Ruta al backend |

El intervalo de despacho debe ser bastante menor que la separación entre avisos: con 15 minutos,
un recordatorio se envía como muy tarde 15 minutos después del momento programado.

El planificador es **estático** (`CELERY_BEAT_SCHEDULE` en settings). No se usa
`django-celery-beat`, que crearía 6 tablas fuera del DER (DEC-11).

## Ejecución

```bash
docker compose up -d worker beat
```

```bash
celery -A config worker --loglevel info
```

```bash
celery -A config beat --loglevel info
```

## Consulta

`GET /api/v1/appointments/{id}/reminders/` — sólo lectura: los recordatorios los programa el
sistema, no el cliente.

## Tests

`tests/test_reminders.py` (46). Ningún envío real. Incluye un test que arranca **un intérprete
aparte** y verifica que el worker descubre las tareas sin importarlas a mano: dentro de la suite
el registro está poblado porque el propio test las importa, lo que enmascararía un fallo de
autodescubrimiento.

> **Nota sobre `on_commit`:** los tests corren en una transacción que se revierte, así que las
> tareas encoladas con `on_commit` no se ejecutan salvo que se capturen con
> `django_capture_on_commit_callbacks`. Eso es lo que evita que el resto de la suite genere
> recordatorios sin querer.
