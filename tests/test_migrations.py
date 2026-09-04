"""Verificacion de las migraciones (FASE 4).

`tests/test_der_contract.py` comprueba que los MODELOS reproducen el DER. Este
modulo comprueba lo que falta: que las MIGRACIONES reproducen esos modelos, que
no falta ninguna, y que el estado que construyen coincide tambien con el DER.

Sin las dos cosas, un modelo correcto con una migracion desactualizada pasaria
desapercibido hasta el despliegue.

No requiere PostgreSQL: `MigrationLoader(None)` carga los archivos de migracion
sin consultar que hay aplicado en la base. La verificacion del esquema fisico
realmente creado vive en `tests/test_schema_postgresql.py`.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db.migrations.autodetector import MigrationAutodetector
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.questioner import NonInteractiveMigrationQuestioner
from django.db.migrations.state import ProjectState
from django.utils import translation

from tests.der_inventory import COLUMN_MAX_LENGTHS, DER

APPS_DEL_PROYECTO = ["core", "people", "medications", "appointments", "massive_load"]


@pytest.fixture(scope="module")
def loader() -> MigrationLoader:
    """Carga las migraciones desde disco, sin tocar la base de datos."""
    return MigrationLoader(None, ignore_no_migrations=True)


@pytest.fixture(scope="module")
def estado_de_migraciones(loader: MigrationLoader) -> ProjectState:
    """Estado del proyecto tras aplicar todas las migraciones."""
    return loader.project_state()


class TestSincronizacion:
    def test_no_quedan_cambios_sin_migrar(
        self, loader: MigrationLoader, estado_de_migraciones: ProjectState
    ) -> None:
        """Equivale a `makemigrations --check`, pero sin necesitar base.

        Si falla, alguien cambio un modelo y no genero la migracion.
        """
        # Las traducciones se desactivan igual que hace `makemigrations`. Con
        # LANGUAGE_CODE=es-co, los `verbose_name` heredados de AbstractBaseUser
        # se traducen en tiempo de ejecucion y el autodetector los veria como
        # cambios, pese a no afectar en absoluto al esquema fisico.
        with translation.override(None):
            autodetector = MigrationAutodetector(
                estado_de_migraciones,
                ProjectState.from_apps(apps),
                NonInteractiveMigrationQuestioner(specified_apps=set(), dry_run=True),
            )
            cambios = autodetector.changes(graph=loader.graph)

        # Solo se comprueban las apps del proyecto: las migraciones de `auth` y
        # `contenttypes` las mantiene Django, no nosotros.
        pendientes = {
            app: [str(op) for m in migraciones for op in m.operations]
            for app, migraciones in cambios.items()
            if app in APPS_DEL_PROYECTO
        }
        assert pendientes == {}, f"Faltan migraciones: {pendientes}"

    @pytest.mark.parametrize("app_label", APPS_DEL_PROYECTO)
    def test_cada_app_tiene_migraciones(
        self, loader: MigrationLoader, app_label: str
    ) -> None:
        assert app_label in loader.migrated_apps

    def test_el_grafo_de_migraciones_es_consistente(
        self, loader: MigrationLoader
    ) -> None:
        """Sin dependencias rotas ni nodos huerfanos: `migrate` es reproducible."""
        loader.graph.validate_consistency()
        assert loader.graph.leaf_nodes()


class TestElEstadoDeLasMigracionesReproduceElDer:
    """Las mismas comprobaciones del contrato, pero sobre las migraciones."""

    @staticmethod
    def _modelo(estado: ProjectState, tabla: str):
        app_label, model_name = DER[tabla]["model"].split(".")
        return estado.apps.get_model(app_label, model_name)

    @pytest.mark.parametrize("tabla", sorted(DER))
    def test_el_nombre_fisico_de_la_tabla(
        self, estado_de_migraciones: ProjectState, tabla: str
    ) -> None:
        assert self._modelo(estado_de_migraciones, tabla)._meta.db_table == tabla

    @pytest.mark.parametrize("tabla", sorted(DER))
    def test_las_columnas_y_su_nulabilidad(
        self, estado_de_migraciones: ProjectState, tabla: str
    ) -> None:
        modelo = self._modelo(estado_de_migraciones, tabla)
        real = {f.column: f.null for f in modelo._meta.concrete_fields}
        assert real == DER[tabla]["columns"]

    @pytest.mark.parametrize("tabla", sorted(DER))
    def test_las_longitudes(
        self, estado_de_migraciones: ProjectState, tabla: str
    ) -> None:
        modelo = self._modelo(estado_de_migraciones, tabla)
        esperadas = COLUMN_MAX_LENGTHS.get(tabla, {})
        reales = {
            f.column: f.max_length
            for f in modelo._meta.concrete_fields
            if f.column in esperadas
        }
        assert reales == esperadas

    @pytest.mark.parametrize("tabla", sorted(DER))
    def test_la_clave_primaria(
        self, estado_de_migraciones: ProjectState, tabla: str
    ) -> None:
        modelo = self._modelo(estado_de_migraciones, tabla)
        assert modelo._meta.pk.column == DER[tabla]["pk"]

    @pytest.mark.parametrize("tabla", sorted(DER))
    def test_las_claves_foraneas(
        self, estado_de_migraciones: ProjectState, tabla: str
    ) -> None:
        modelo = self._modelo(estado_de_migraciones, tabla)
        reales = {
            f.column: f.related_model._meta.db_table
            for f in modelo._meta.concrete_fields
            if f.is_relation
        }
        assert reales == DER[tabla]["foreign_keys"]


class TestRestricciones:
    ESPERADAS = {
        "uq_patient_pathology",
        "uq_patient_primary_pathology",
        "ck_audit_log_action",
        "ck_clinical_history_entry_type",
        "ck_treatment_plan_status",
        "ck_appointment_status",
        "ck_appointment_priority",
        "ck_appointment_reminder_channel",
        "ck_appointment_reminder_status",
        "ck_import_batch_status",
        "ck_import_batch_row_status",
    }

    def test_las_migraciones_crean_todas_las_restricciones(
        self, estado_de_migraciones: ProjectState
    ) -> None:
        nombres = set()
        for spec in DER.values():
            app_label, model_name = spec["model"].split(".")
            modelo = estado_de_migraciones.apps.get_model(app_label, model_name)
            nombres.update(c.name for c in modelo._meta.constraints)
        assert nombres == self.ESPERADAS

    def test_las_migraciones_crean_todos_los_indices(
        self, estado_de_migraciones: ProjectState
    ) -> None:
        # DEC-05: indices no unicos autorizados, ninguno mas.
        esperados = {
            "ix_audit_log_entity",
            "ix_audit_log_created_at",
            "ix_patient_name",
            "ix_patient_is_active",
            "ix_appointment_scheduled_at",
            "ix_appointment_patient_date",
            "ix_reminder_status_date",
        }
        nombres = set()
        for spec in DER.values():
            app_label, model_name = spec["model"].split(".")
            modelo = estado_de_migraciones.apps.get_model(app_label, model_name)
            nombres.update(i.name for i in modelo._meta.indexes)
        assert nombres == esperados


class TestSinEntidadesFueraDelDer:
    def test_las_migraciones_no_crean_ninguna_tabla_de_mas(
        self, estado_de_migraciones: ProjectState
    ) -> None:
        """Ni tablas M2M ocultas, ni tablas de django-celery-beat, ni nada."""
        tablas = {
            modelo._meta.db_table
            for modelo in estado_de_migraciones.apps.get_models()
            if modelo._meta.app_label in APPS_DEL_PROYECTO
        }
        assert tablas == set(DER)
