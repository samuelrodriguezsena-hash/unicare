"""Entorno de produccion.

Endurece la configuracion y activa Sentry. Agnostico de proveedor cloud: no hay
ninguna dependencia de AWS, GCP, Azure, Render, Railway ni Fly. Todo el
acoplamiento a infraestructura pasa por DATABASE_URL y REDIS_URL.
"""

from __future__ import annotations

import os

from .base import *
from .base import ImproperlyConfigured, env, env_bool, env_int

DEBUG = False

# En produccion ALLOWED_HOSTS es obligatorio Y no puede quedar vacio.
#
# `env()` solo protesta si la variable NO existe; una cadena vacia la
# satisface y dejaria `ALLOWED_HOSTS = []`, con lo que Django rechazaria TODAS
# las peticiones con un 400. Es preferible fallar al arrancar, con un mensaje
# claro, que desplegar algo que responde 400 a todo.
ALLOWED_HOSTS = [h.strip() for h in env("DJANGO_ALLOWED_HOSTS").split(",") if h.strip()]

if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS esta vacia. En produccion debe listar los "
        "dominios servidos, separados por comas."
    )

# Las sondas locales (HEALTHCHECK del contenedor, probes de un orquestador)
# llegan con `Host: localhost` o `Host: 127.0.0.1`, que no son el dominio
# publico. Sin esto Django responde 400 a TODAS ellas y el contenedor queda
# marcado como unhealthy para siempre, aunque este perfectamente sano.
#
# No debilita la proteccion: ALLOWED_HOSTS evita que un Host manipulado acabe
# en URLs absolutas generadas por el servidor. Quien envie `Host: localhost`
# solo consigue que los enlaces de paginacion apunten a su propia maquina.
ALLOWED_HOSTS += [h for h in ("localhost", "127.0.0.1") if h not in ALLOWED_HOSTS]

# ---------------------------------------------------------------------------
# HTTPS y cabeceras de seguridad
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)

# Los health checks quedan exentos del redirect a HTTPS.
#
# Una sonda local habla HTTP plano contra el contenedor: sin esta exencion
# recibe un 301 en lugar de la respuesta. Un 301 es un "exito" para curl -f y
# para las probes HTTP de los orquestadores, asi que la sonda pasaria sin haber
# comprobado nada -- el redirect lo emite el middleware antes de llegar a la
# vista. Peor que fallar: aparentar salud.
#
# Los dos endpoints son publicos y no devuelven informacion clinica.
SECURE_REDIRECT_EXEMPT = [r"^api/v1/health/$", r"^api/v1/health/ready/$"]
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
X_FRAME_OPTIONS = "DENY"

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
# En produccion la API responde solo JSON.
#
# El navegador de DRF es una herramienta de desarrollo: renderiza formularios de
# escritura para cada endpoint y expone la superficie de la API en HTML. Ademas
# es el unico consumidor de ficheros estaticos del proyecto (el admin de Django
# no esta instalado), asi que quitarlo deja el contenedor sin nada que servir
# como estatico.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
}

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
# El DSN NUNCA esta hardcodeado. Si esta vacio, Sentry queda desactivado.
#
# La inicializacion vive en `apps.core.observability` para que la logica de
# saneado sea testeable sin arrancar Sentry. Ver ese modulo: el saneado es
# agresivo porque este sistema maneja informacion clinica.
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")

if SENTRY_DSN:
    from apps.core.observability import init_sentry

    init_sentry()
