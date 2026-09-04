# Observabilidad

Sentry para excepciones, errores de integración, fallos de Celery y rendimiento.

## Activación

Se activa **sólo si hay `SENTRY_DSN`**. Sin él, `init_sentry()` es un no-op y `capture_exception`
no hace nada: los entornos sin observabilidad funcionan igual.

| Variable | Default | Notas |
|---|---|---|
| `SENTRY_DSN` | *(vacío)* | Vacío ⇒ desactivado. **Nunca en el repositorio** |
| `SENTRY_ENVIRONMENT` | `production` | |
| `SENTRY_RELEASE` | *(vacío)* | Para correlacionar errores con despliegues |
| `SENTRY_TRACES_SAMPLE_RATE` | `0.1` | Muestreo de rendimiento |

La inicialización vive en `apps/core/observability.py`, **no en las settings**, para que la
lógica de saneado se pueda probar sin arrancar Sentry. `config/settings/production.py` sólo la
invoca.

## Qué se registra

| Fuente | Cómo |
|---|---|
| Excepciones no controladas | `DjangoIntegration` |
| Fallos de tareas Celery | `CeleryIntegration` |
| `logger.error(...)` | `LoggingIntegration` (`event_level=ERROR`) |
| Errores de la API de fármacos | `capture_exception` explícito en el cliente |
| Errores de Gemini | `capture_exception` explícito en `GeminiService` |
| Rendimiento | `traces_sample_rate` |

Los errores **esperables de validación** no generan eventos: un query parameter inválido o un
`400` del servicio externo son errores del cliente, no fallos de infraestructura, y llenarían
Sentry de ruido.

## Privacidad — lo importante

Un servicio de observabilidad es **un tercero**, y lo que se le manda sale de nuestra
infraestructura. Con información clínica de por medio, el saneado es agresivo por defecto.

### Nunca sale

- **El cuerpo de la petición.** `sentry-sdk` lo captura por defecto
  (`max_request_body_size="medium"`) — y ese cuerpo lleva diagnósticos, notas clínicas y datos
  de contacto. Se fuerza **`"never"`**.
- **Cabeceras, cookies y query string.** Un filtro puede llevar el nombre o la identificación de
  un paciente.
- **Nombre, email o IP del usuario.** `send_default_pii=False` más un `before_send` que deja el
  objeto `user` reducido a su ID.
- **Cualquier clave sensible o clínica**, por coincidencia parcial: cubre `GEMINI_API_KEY`,
  `HTTP_AUTHORIZATION`, `patient_email`, `old_values`, `notes`… Se redactan en `extra`,
  `contexts`, `tags` y en los datos de las migas de pan.

### Sí sale

Excepciones y sus trazas, el endpoint y el método, y el **ID** del usuario responsable.
Suficiente para diagnosticar sin exfiltrar historiales.

`before_send` es la **última barrera**: aunque una integración capture algo de más, ahí se
elimina.

## Trazabilidad

La documentación pide poder trazar request, usuario, entidad, operación, error, integración
externa y tarea Celery. Se cubre así:

| Qué | Dónde |
|---|---|
| Request, error, tarea Celery | Sentry (endpoint, método, traza, evento) |
| Usuario responsable | ID en el evento de Sentry, y `user_id` completo en `AUDIT_LOG` |
| Entidad y operación | `AUDIT_LOG` — ver [`AUDITORIA.md`](AUDITORIA.md) |
| Integración externa | `capture_exception` en los clientes de fármacos y Gemini |

El reparto es deliberado: **el detalle de qué se cambió vive en `AUDIT_LOG`, dentro de nuestra
base**, no en un tercero. Sentry sólo recibe lo necesario para diagnosticar el fallo.

El ID del usuario lo obtiene `before_send` del mismo `ContextVar` que usa la auditoría, así que
un error dentro de una petición autenticada queda atribuido sin configuración adicional.

## Verificación

```bash
python -m pytest tests/test_observability.py -v
```

51 tests, sin PostgreSQL y sin inicializar Sentry: prueban la lógica de saneado, que es
exactamente lo que hay que verificar aquí. Cobertura del 100 % en el módulo.

Incluyen un test que recorre `apps/` y `config/` y falla si aparece un DSN hardcodeado.

Para comprobar la configuración de producción sin enviar nada real:

```bash
DJANGO_SETTINGS_MODULE=config.settings.production SENTRY_DSN=... python manage.py check --deploy
```
