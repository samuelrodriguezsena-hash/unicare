"""Configuracion comun a todos los entornos de UniCare.

Regla absoluta del proyecto: CERO SECRETOS EN EL REPOSITORIO.
Todo valor sensible o dependiente del entorno se lee de variables de entorno.
Ver `.env.example` para el inventario completo.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url
from celery.schedules import crontab
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Carga .env solo si existe (desarrollo local). En Docker y en cloud las
# variables llegan por el entorno del proceso.
load_dotenv(BASE_DIR / ".env", override=False)


# ---------------------------------------------------------------------------
# Helpers de entorno
# ---------------------------------------------------------------------------
class ImproperlyConfigured(Exception):
    """Falta una variable de entorno obligatoria."""


def env(name: str, default: str | None = None) -> str:
    """Devuelve una variable de entorno; falla si es obligatoria y falta."""
    value = os.environ.get(name, default)
    if value is None:
        raise ImproperlyConfigured(
            f"La variable de entorno {name} es obligatoria y no esta definida."
        )
    return value


def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    return int(raw) if raw not in (None, "") else default


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_json_dict(name: str) -> dict[str, str]:
    """Lee un objeto JSON de cadena a cadena. Vacio si la variable no esta.

    Falla al arrancar si el JSON es invalido o no tiene esa forma: un mapeo mal
    escrito que se ignorase en silencio daria un fallo mucho mas adelante y sin
    relacion aparente con su causa.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return {}

    import json

    try:
        valor = json.loads(raw)
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} no es JSON valido: {error}") from error

    if not isinstance(valor, dict) or not all(
        isinstance(clave, str) and isinstance(contenido, str)
        for clave, contenido in valor.items()
    ):
        raise ImproperlyConfigured(
            f"{name} debe ser un objeto JSON de cadena a cadena: " '{"clave": "valor"}.'
        )
    return valor


# ---------------------------------------------------------------------------
# Nucleo Django
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")

# django.contrib.admin queda EXCLUIDO deliberadamente: `core.User` no usa
# PermissionsMixin (ver docs/DECISIONS.md, C-02 opcion 3), por lo que el admin
# de Django no es utilizable. El proyecto no lo requiere.
DJANGO_APPS = [
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "django_filters",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.core",
    "apps.people",
    "apps.medications",
    "apps.appointments",
    "apps.massive_load",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Ultimo: expone la peticion a la auditoria (apps.core.context).
    "apps.core.middleware.CurrentUserMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
            ],
        },
    },
]

# El DER define la entidad USER. Ver docs/DECISIONS.md seccion 3: las unicas
# columnas anadidas al DER son `password` y `last_login`.
AUTH_USER_MODEL = "core.User"

_VALIDATORS_MODULE = "django.contrib.auth.password_validation"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": f"{_VALIDATORS_MODULE}.UserAttributeSimilarityValidator"},
    {"NAME": f"{_VALIDATORS_MODULE}.MinimumLengthValidator"},
    {"NAME": f"{_VALIDATORS_MODULE}.CommonPasswordValidator"},
    {"NAME": f"{_VALIDATORS_MODULE}.NumericPasswordValidator"},
]

# Usuario tecnico responsable de las operaciones automaticas (Celery beat,
# comandos de gestion). Ver docs/DECISIONS.md, C-04. Se crea por data migration.
SYSTEM_USERNAME = env("SYSTEM_USERNAME", "system")

# DEC-17: ni el DER ni la documentacion funcional definen el formato del numero
# de identificacion de un paciente. No se impone uno rigido: el patron es
# configurable y el valor por defecto solo descarta lo inequivocamente invalido.
IDENTIFICATION_NUMBER_PATTERN = env(
    "IDENTIFICATION_NUMBER_PATTERN", r"^[A-Za-z0-9][A-Za-z0-9.\-]{1,49}$"
)

# DEC-33: el nombre de las columnas del archivo de carga masiva no lo define
# nadie -- ni el DER ni la documentacion funcional. El contrato canonico vive en
# `apps.massive_load.parsers` y esta alineado con los snapshots de
# `IMPORT_BATCH_ROW`, pero los archivos reales vendran exportados de otro
# sistema y traeran las cabeceras que traigan.
#
# Este mapeo `cabecera del archivo -> columna canonica` permite adaptarse a
# ellos SIN tocar codigo ni desplegar. Vacio por defecto: inventar aqui una
# traduccion al castellano seria otra suposicion, y ya hay una de mas.
#
#   MASSIVE_LOAD_COLUMN_ALIASES='{"numero_identificacion": "identification_number"}'
#
# Que el destino de cada alias exista se comprueba en `massive_load.apps`:
# aqui todavia no se pueden importar modulos de las apps.
MASSIVE_LOAD_COLUMN_ALIASES = env_json_dict("MASSIVE_LOAD_COLUMN_ALIASES")

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Internacionalizacion
# ---------------------------------------------------------------------------
LANGUAGE_CODE = env("DJANGO_LANGUAGE_CODE", "es-co")
TIME_ZONE = env("DJANGO_TIME_ZONE", "UTC")
USE_I18N = True
# DEC-12: USE_TZ obligatorio -> PostgreSQL timestamptz. Los recordatorios a
# -48h/-24h dependen de datetimes con zona horaria.
USE_TZ = True


# ---------------------------------------------------------------------------
# Estaticos
# ---------------------------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"


# ---------------------------------------------------------------------------
# Base de datos (PostgreSQL)
# ---------------------------------------------------------------------------
# El proyecto NUNCA asume SQLite. `DATABASE_URL` es obligatoria.
DATABASES = {
    "default": dj_database_url.parse(
        env("DATABASE_URL"),
        conn_max_age=env_int("DATABASE_CONN_MAX_AGE", 600),
        conn_health_checks=True,
    )
}


# ---------------------------------------------------------------------------
# Redis: cache y broker de Celery
# ---------------------------------------------------------------------------
REDIS_URL = env("REDIS_URL")

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": REDIS_URL,
        "KEY_PREFIX": "unicare",
    }
}


# ---------------------------------------------------------------------------
# Celery
# ---------------------------------------------------------------------------
CELERY_BROKER_URL = env("CELERY_BROKER_URL", REDIS_URL)
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", REDIS_URL)
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = env_int("CELERY_TASK_TIME_LIMIT", 600)
CELERY_TASK_SOFT_TIME_LIMIT = env_int("CELERY_TASK_SOFT_TIME_LIMIT", 540)
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

# DEC-11: beat_schedule estatico. django-celery-beat crearia tablas fuera
# del DER, lo que el contrato prohibe.
#
# Esta es la UNICA fuente del planificador: `config/celery.py` no debe
# reasignar `app.conf.beat_schedule`, porque `config_from_object` lee las
# settings de Django de forma perezosa y volveria a pisar la asignacion.
#
# El intervalo del despacho debe ser bastante menor que la separacion entre
# avisos: con 15 minutos, un recordatorio se envia como muy tarde 15 minutos
# despues del momento programado.
# `beat` escribe aqui la ultima ejecucion de cada tarea. En un contenedor
# conviene apuntarlo a un volumen: si el fichero se pierde en cada reinicio,
# beat vuelve a disparar el despacho nada mas arrancar.
CELERY_BEAT_SCHEDULE_FILENAME = env(
    "CELERY_BEAT_SCHEDULE_FILENAME", str(BASE_DIR / ".celerybeat-schedule")
)
CELERY_BEAT_SCHEDULE: dict[str, dict] = {
    "dispatch-due-reminders": {
        "task": "apps.appointments.tasks.dispatch_due_reminders",
        "schedule": crontab(minute=f"*/{env_int('REMINDER_DISPATCH_MINUTES', 15)}"),
    },
}

# Offsets de los recordatorios, en horas antes de la cita. La documentacion
# exige 48h y 24h; se deja configurable.
REMINDER_OFFSETS_HOURS = [
    int(value) for value in env_list("REMINDER_OFFSETS_HOURS", "48,24")
]

# Backend de notificaciones. El dominio de citas no conoce ningun proveedor:
# integrar email o SMS de verdad consiste en escribir un backend y apuntar aqui.
NOTIFICATION_BACKEND = env(
    "NOTIFICATION_BACKEND",
    "apps.core.services.notifications.LoggingNotificationBackend",
)


# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
    ),
    # C-03: sin roles, pero ningun anonimo ejecuta operaciones administrativas.
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_FILTER_BACKENDS": (
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": env_int("API_PAGE_SIZE", 25),
    "EXCEPTION_HANDLER": "apps.core.exceptions.api_exception_handler",
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(
        minutes=env_int("JWT_ACCESS_TOKEN_LIFETIME", 15)
    ),
    "REFRESH_TOKEN_LIFETIME": timedelta(
        minutes=env_int("JWT_REFRESH_TOKEN_LIFETIME", 1440)
    ),
    # DEC-35: NI rotacion NI lista negra.
    #
    # `ROTATE_REFRESH_TOKENS=True` requiere la app `token_blacklist` de
    # simplejwt: la rotacion llama a `refresh.outstand()`, que escribe en
    # `OutstandingToken`. Esa app anade DOS tablas que el DER no contempla, asi
    # que no se instala; sin ella, activar la rotacion hace que refrescar falle
    # con un 500.
    #
    # Consecuencias, documentadas y asumidas:
    #   * un refresh token sigue valido hasta que caduca, y no se puede
    #     revocar: el "logout" es del lado del cliente;
    #   * la mitigacion es la vida corta de los tokens, sobre todo la del
    #     access (15 minutos por defecto).
    "ROTATE_REFRESH_TOKENS": False,
    "BLACKLIST_AFTER_ROTATION": False,
    # `user_id` es la PK que define el DER; simplejwt asume `id` por defecto.
    "USER_ID_FIELD": "user_id",
    "USER_ID_CLAIM": "user_id",
    "SIGNING_KEY": SECRET_KEY,
}


# ---------------------------------------------------------------------------
# CORS / CSRF
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = env_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")


# ---------------------------------------------------------------------------
# Integraciones externas
# ---------------------------------------------------------------------------
# API de farmacos. C-07: la URL documentada es un placeholder, por lo que NO
# hay valor por defecto. Es obligatoria y nunca se escribe en el codigo.
FARMACOS_API_BASE_URL = env("FARMACOS_API_BASE_URL")
FARMACOS_API_TIMEOUT = float(env("FARMACOS_API_TIMEOUT", "5"))
FARMACOS_CACHE_TTL = env_int("FARMACOS_CACHE_TTL", 900)
# La API es hoy publica y de solo lectura. Si en el futuro exige credencial,
# basta con definir esta variable: el cliente la envia como Bearer y no hay que
# tocar codigo. Vacia = sin autenticacion.
FARMACOS_API_KEY = os.environ.get("FARMACOS_API_KEY", "")

# Gemini. C-08: el patron de invocacion queda confinado a GeminiService._invoke.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = env("GEMINI_MODEL", "gemini-3.7-flash")
GEMINI_TIMEOUT = float(env("GEMINI_TIMEOUT", "15"))

# Texto obligatorio que acompana a TODA salida de IA. Regla clinica del
# proyecto: la IA nunca es autoridad clinica.
AI_SUGGESTION_LABEL = "SUGERENCIA GENERADA POR IA"
AI_SUGGESTION_DISCLAIMER = (
    "Esta informacion es una sugerencia generada por inteligencia artificial y "
    "requiere validacion por parte de un profesional clinico. No constituye una "
    "prescripcion ni una decision medica."
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
# Privacidad: el sistema maneja informacion clinica. No se registran secretos
# ni datos clinicos en los logs; los servicios loguean identificadores, no
# contenido de historiales.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(name)s %(message)s",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": env("DJANGO_LOG_LEVEL", "INFO"),
    },
    "loggers": {
        "django.db.backends": {"level": "WARNING", "propagate": True},
    },
}
