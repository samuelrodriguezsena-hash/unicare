"""Aplicacion Celery de UniCare.

El planificador se define EXCLUSIVAMENTE en `config/settings/base.py`
(`CELERY_BEAT_SCHEDULE`). No se reasigna `app.conf.beat_schedule` aqui:
`config_from_object` lee las settings de Django de forma perezosa, asi que una
asignacion en este modulo quedaria silenciosamente pisada.

DEC-11: scheduling estatico, no `django-celery-beat`, que crearia tablas fuera
del DER.
"""

from __future__ import annotations

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("unicare")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task(bind=True, name="config.debug_task")
def debug_task(self) -> str:
    """Tarea trivial para verificar que el worker responde."""
    return f"ok: {self.request.id}"
