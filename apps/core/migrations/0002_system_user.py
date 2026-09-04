"""Usuario tecnico `system`.

docs/DECISIONS.md, C-04: `AUDIT_LOG.user_id` es NOT NULL en el DER, pero las
tareas de Celery y los comandos de gestion no tienen usuario autenticado. En vez
de relajar la nulabilidad del DER, se crea un usuario tecnico al que se atribuyen
esas operaciones.

No puede autenticarse: se le fija una contrasena inutilizable.
"""

from __future__ import annotations

from django.conf import settings
from django.db import migrations


def crear_usuario_system(apps, schema_editor) -> None:
    User = apps.get_model("core", "User")
    username = settings.SYSTEM_USERNAME
    if User.objects.filter(username=username).exists():
        return
    usuario = User(username=username, is_active=True)
    # `set_unusable_password` no existe en el modelo historico; se replica su
    # efecto, que es simplemente un hash con el prefijo de "no utilizable".
    usuario.password = "!"
    usuario.save()


def borrar_usuario_system(apps, schema_editor) -> None:
    User = apps.get_model("core", "User")
    # Solo se borra si no dejo rastro en la auditoria: `AUDIT_LOG.user_id` usa
    # PROTECT, y perder registros de auditoria al revertir seria inaceptable.
    AuditLog = apps.get_model("core", "AuditLog")
    usuario = User.objects.filter(username=settings.SYSTEM_USERNAME).first()
    if usuario and not AuditLog.objects.filter(user_id=usuario.pk).exists():
        usuario.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(crear_usuario_system, borrar_usuario_system),
    ]
