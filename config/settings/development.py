"""Entorno de desarrollo."""

from .base import *
from .base import env_bool, env_list

DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0,web")

# En desarrollo se permite cualquier origen para facilitar el trabajo con un
# frontend local. En produccion NUNCA.
CORS_ALLOW_ALL_ORIGINS = True

# Las tareas se ejecutan contra el worker real de docker-compose.
CELERY_TASK_ALWAYS_EAGER = env_bool("CELERY_TASK_ALWAYS_EAGER", False)
