"""Enganche de la auditoria mediante signals.

La documentacion normativa admite signals, middleware o capa de servicio. Se usa
la combinacion de los tres: el middleware aporta el usuario, las signals
garantizan que NINGUNA operacion critica se escape (tambien las que no pasan por
un servicio), y `AuditService` centraliza la escritura.

Que se audita: las 13 entidades de dominio del DER. `AUDIT_LOG` NO se audita a
si mismo, para no entrar en recursion infinita.

Las signals se conectan con `sender` explicito, asi que NO se disparan con los
modelos historicos que Django usa dentro de las migraciones. Eso es deliberado:
una data migration no debe generar auditoria.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Model
from django.db.models.signals import post_delete, post_save, pre_save

from apps.core.context import get_current_user
from apps.core.services.audit import AuditService, serialize_instance

# Atributo donde se deja la instantanea previa entre `pre_save` y `post_save`.
_PREVIOUS = "_unicare_audit_previous"

# `app_label.ModelName` de las entidades auditadas. `core.AuditLog` queda fuera.
AUDITED_MODELS: tuple[str, ...] = (
    "core.User",
    "people.Patient",
    "people.Pathology",
    "people.PatientPathology",
    "people.ClinicalHistory",
    "people.ClinicalHistoryEntry",
    "people.Note",
    "medications.TreatmentPlan",
    "medications.TreatmentPlanMedication",
    "appointments.Appointment",
    "appointments.AppointmentReminder",
    "massive_load.ImportBatch",
    "massive_load.ImportBatchRow",
)


def _stamp_auditor_fields(instance: Model, creando: bool) -> None:
    """Rellena `created_by` / `updated_by` en los modelos que los tienen.

    Solo afecta a las 11 tablas a las que el DER da esos campos. No se pisa un
    valor que el codigo haya fijado explicitamente.
    """
    if not hasattr(instance, "updated_by_id"):
        return

    user = get_current_user()
    if user is None:
        return

    if creando and instance.created_by_id is None:
        instance.created_by_id = user.pk
    instance.updated_by_id = user.pk


def _pre_save(sender: type[Model], instance: Model, **kwargs: Any) -> None:
    """Captura el estado anterior y sella los campos de auditoria."""
    if kwargs.get("raw"):
        # Carga de fixtures: se escribe tal cual, sin efectos secundarios.
        return

    creando = instance._state.adding or instance.pk is None
    previo: dict[str, Any] | None = None
    if not creando:
        anterior = sender.objects.filter(pk=instance.pk).first()
        # `anterior` puede ser None si se guarda con una PK fijada a mano.
        previo = serialize_instance(anterior) if anterior is not None else None

    setattr(instance, _PREVIOUS, previo)
    _stamp_auditor_fields(instance, creando=previo is None)


def _post_save(
    sender: type[Model], instance: Model, created: bool, **kwargs: Any
) -> None:
    if kwargs.get("raw"):
        return

    previo = getattr(instance, _PREVIOUS, None)
    if created or previo is None:
        AuditService.log_create(instance)
    else:
        AuditService.log_update(instance, previo)


def _post_delete(sender: type[Model], instance: Model, **kwargs: Any) -> None:
    AuditService.log_delete(instance, serialize_instance(instance))


def connect_audit_signals() -> None:
    """Conecta las signals. Lo invoca `CoreConfig.ready()`."""
    from django.apps import apps as django_apps

    for label in AUDITED_MODELS:
        model = django_apps.get_model(label)
        uid = f"unicare_audit_{label}"
        pre_save.connect(_pre_save, sender=model, dispatch_uid=f"{uid}_pre_save")
        post_save.connect(_post_save, sender=model, dispatch_uid=f"{uid}_post_save")
        post_delete.connect(
            _post_delete, sender=model, dispatch_uid=f"{uid}_post_delete"
        )
