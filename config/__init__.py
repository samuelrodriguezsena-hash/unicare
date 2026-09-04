"""Paquete de configuracion de UniCare.

Importar `celery_app` aqui garantiza que la app de Celery quede registrada al
arrancar Django (necesario para el decorador @shared_task de las apps).
"""

from .celery import app as celery_app

__all__ = ("celery_app",)
