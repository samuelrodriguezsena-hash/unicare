from __future__ import annotations

from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Core"

    def ready(self) -> None:
        # Se conectan aqui, no al importar el modulo, para que todos los
        # modelos esten cargados.
        from apps.core.audit import connect_audit_signals

        connect_audit_signals()
