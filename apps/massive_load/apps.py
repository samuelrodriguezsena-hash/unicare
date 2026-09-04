from __future__ import annotations

from django.apps import AppConfig
from django.core.exceptions import ImproperlyConfigured


class MassiveLoadConfig(AppConfig):
    name = "apps.massive_load"
    label = "massive_load"
    verbose_name = "MassiveLoad"

    def ready(self) -> None:
        """Comprueba que los alias de columnas apuntan a algo real (DEC-33).

        Un alias con el destino mal escrito no rompe nada al arrancar: sigue
        siendo una cabecera desconocida y el parser la ignora en silencio, asi
        que el sintoma seria una importacion que falla por "falta una columna
        obligatoria" que en el archivo esta. Es mucho mejor no arrancar.
        """
        from apps.massive_load.parsers import COLUMNAS_RECONOCIDAS, alias_configurados

        invalidos = {
            origen: destino
            for origen, destino in alias_configurados().items()
            if destino not in COLUMNAS_RECONOCIDAS
        }
        if invalidos:
            raise ImproperlyConfigured(
                "MASSIVE_LOAD_COLUMN_ALIASES apunta a columnas que no existen: "
                + ", ".join(f"{o} -> {d}" for o, d in sorted(invalidos.items()))
                + ". Columnas validas: "
                + ", ".join(sorted(COLUMNAS_RECONOCIDAS))
                + "."
            )
