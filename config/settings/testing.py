"""Entorno de testing.

Los defaults se fijan ANTES de importar `base`, porque `base` lee las variables
de entorno en tiempo de importacion. Asi el pipeline de CI no necesita un `.env`
y, sobre todo, no necesita credenciales reales: ninguna de estas es un secreto.
"""

from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SECRET_KEY", "insecure-testing-key-not-a-secret")
os.environ.setdefault("DJANGO_DEBUG", "False")
os.environ.setdefault(
    "DATABASE_URL", "postgres://unicare:unicare@localhost:5432/unicare_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/1")
# C-07: la API de farmacos NUNCA se llama de verdad en tests. Este host existe
# solo para que respx tenga algo que interceptar.
os.environ.setdefault("FARMACOS_API_BASE_URL", "https://farmacos.invalid")
os.environ.setdefault("GEMINI_API_KEY", "")

from .base import *

DEBUG = False
ALLOWED_HOSTS = ["*"]

# Las tareas se ejecutan en el mismo proceso: los tests verifican el flujo, y
# el scheduling/reintento se testea de forma explicita sobre la propia tarea.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Cache local: los tests de caching del cliente de farmacos no deben depender
# de un Redis levantado.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unicare-testing",
    }
}

# Hasher rapido: acelera notablemente las factories de usuarios.
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Sentry desactivado en tests.
SENTRY_DSN = ""
