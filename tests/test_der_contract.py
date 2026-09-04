"""Verificacion del contrato del DER contra los modelos Django.

El DER es un contrato. Este modulo lo hace ejecutable: compara, tabla por tabla
y columna por columna, el inventario de `tests/der_inventory.py` con la
metainformacion de los modelos.

Un fallo aqui significa que la implementacion se ha desviado del diagrama.
No se corrige el test: se corrige el modelo, o se documenta y autoriza la
desviacion en docs/DECISIONS.md seccion 3.

No requiere PostgreSQL: opera sobre `Model._meta`.
"""

from __future__ import annotations

import pytest
from django.apps import apps
from django.db.models import Model, UniqueConstraint

from tests.der_inventory import (
    COLUMN_MAX_LENGTHS,
    DER,
    TABLES_WITH_AUDITOR,
    TABLES_WITHOUT_AUDITOR,
)

AUDITOR_COLUMNS = {"created_at", "updated_at", "created_by", "updated_by"}


def get_model(label: str) -> type[Model]:
    app_label, model_name = label.split(".")
    return apps.get_model(app_label, model_name)


TABLES = sorted(DER)


@pytest.mark.parametrize("table", TABLES)
class TestEstructura:
    def test_el_nombre_fisico_de_la_tabla_coincide(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        assert model._meta.db_table == table

    def test_la_clave_primaria_coincide(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        pk = model._meta.pk
        assert pk is not None
        assert pk.column == DER[table]["pk"]
        # El DER usa PK surrogate bigint en las 14 tablas.
        assert pk.get_internal_type() == "BigAutoField"

    def test_no_sobran_ni_faltan_columnas(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        actuales = {f.column for f in model._meta.concrete_fields}
        esperadas = set(DER[table]["columns"])
        assert actuales == esperadas, (
            f"{table}: sobran {sorted(actuales - esperadas)}, "
            f"faltan {sorted(esperadas - actuales)}"
        )

    def test_la_nulabilidad_coincide(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        # Criterio del proyecto: NOT NULL solo donde el DER lo escribe.
        real = {f.column: f.null for f in model._meta.concrete_fields}
        assert real == DER[table]["columns"]

    def test_las_longitudes_coinciden(self, table: str) -> None:
        """`varchar(N)` del DER -> max_length=N; `varchar` sin N -> TextField.

        Sin este test, un `EmailField` (que impone un max_length=254 propio de
        Django) pasaria inadvertido donde el DER no declara longitud.
        """
        model = get_model(DER[table]["model"])
        esperadas = COLUMN_MAX_LENGTHS.get(table, {})
        reales = {
            f.column: f.max_length
            for f in model._meta.concrete_fields
            if f.column in esperadas
        }
        assert reales == esperadas

    def test_toda_columna_de_texto_declara_su_longitud_esperada(
        self, table: str
    ) -> None:
        """Ninguna columna de texto queda fuera del inventario de longitudes."""
        model = get_model(DER[table]["model"])
        de_texto = {
            f.column
            for f in model._meta.concrete_fields
            if f.get_internal_type() in {"CharField", "TextField", "EmailField"}
        }
        assert de_texto == set(COLUMN_MAX_LENGTHS.get(table, {}))

    def test_las_columnas_unique_simples_coinciden(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        reales = {
            f.column
            for f in model._meta.concrete_fields
            if f.unique and not f.primary_key
        }
        assert reales == set(DER[table]["unique"])

    def test_las_restricciones_unique_compuestas_coinciden(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        columna_de = {f.name: f.column for f in model._meta.concrete_fields}
        reales = {
            tuple(sorted(columna_de.get(name, name) for name in c.fields))
            for c in model._meta.constraints
            if isinstance(c, UniqueConstraint) and c.condition is None
        }
        esperadas = {tuple(sorted(cols)) for cols in DER[table]["unique_together"]}
        assert reales == esperadas

    def test_las_claves_foraneas_apuntan_donde_dice_el_der(self, table: str) -> None:
        model = get_model(DER[table]["model"])
        reales = {
            f.column: f.related_model._meta.db_table
            for f in model._meta.concrete_fields
            if f.is_relation
        }
        assert reales == DER[table]["foreign_keys"]


class TestAuditoria:
    @pytest.mark.parametrize("table", sorted(TABLES_WITH_AUDITOR))
    def test_las_tablas_auditadas_tienen_los_cuatro_campos(self, table: str) -> None:
        columnas = set(DER[table]["columns"])
        assert AUDITOR_COLUMNS <= columnas

    @pytest.mark.parametrize("table", sorted(TABLES_WITHOUT_AUDITOR))
    def test_las_tablas_no_auditadas_no_los_tienen(self, table: str) -> None:
        # D-02: APPOINTMENT_REMINDER, AUDIT_LOG y USER no llevan auditoria.
        # AUDIT_LOG y USER si tienen created_at, pero no los otros tres.
        columnas = set(DER[table]["columns"])
        assert "updated_by" not in columnas
        assert "created_by" not in columnas

    def test_la_particion_cubre_las_catorce_tablas(self) -> None:
        assert TABLES_WITH_AUDITOR | TABLES_WITHOUT_AUDITOR == set(DER)
        assert not TABLES_WITH_AUDITOR & TABLES_WITHOUT_AUDITOR


class TestReglasEmbebidasEnElDer:
    def test_max_una_patologia_principal_por_paciente(self) -> None:
        """A-04: traduccion de "bool; max 1 primary/patient" del propio DER."""
        model = get_model("people.PatientPathology")
        parciales = [
            c
            for c in model._meta.constraints
            if isinstance(c, UniqueConstraint) and c.condition is not None
        ]
        assert len(parciales) == 1
        constraint = parciales[0]
        assert constraint.name == "uq_patient_primary_pathology"
        assert constraint.fields == ("patient",)

    def test_no_existe_ningun_many_to_many(self) -> None:
        """El DER modela las asociaciones como entidades explicitas."""
        for table, spec in DER.items():
            model = get_model(spec["model"])
            assert not model._meta.many_to_many, f"{table} declara un M2M"

    def test_no_hay_catalogo_local_de_medicamentos(self) -> None:
        """El farmaco se referencia por id externo, nunca por FK local."""
        model = get_model("medications.TreatmentPlanMedication")
        relaciones = {f.column for f in model._meta.concrete_fields if f.is_relation}
        assert relaciones == {"treatment_plan_id", "created_by", "updated_by"}
        # No existe una tabla catalogo de farmacos: la unica tabla que los
        # menciona es la asociativa del plan de tratamiento.
        assert {"medication", "medications", "drug", "farmaco"} & set(DER) == set()
        assert model._meta.get_field("external_medication_id").is_relation is False

    def test_ninguna_tabla_es_unmanaged(self) -> None:
        """`managed=False` esta prohibido: Django debe poder migrar el esquema."""
        for spec in DER.values():
            assert get_model(spec["model"])._meta.managed


class TestTotales:
    def test_hay_exactamente_catorce_tablas(self) -> None:
        assert len(DER) == 14

    def test_el_numero_de_columnas_fisicas_coincide(self) -> None:
        total = sum(len(spec["columns"]) for spec in DER.values())
        # 139 columnas fisicas del DER + las 2 anadidas a `user`
        # (docs/DECISIONS.md seccion 3).
        assert total == 141

    def test_el_numero_de_claves_foraneas_coincide(self) -> None:
        fks = [fk for spec in DER.values() for fk in spec["foreign_keys"]]
        auditoria = [fk for fk in fks if fk in {"created_by", "updated_by"}]
        assert len(auditoria) == 22  # 11 tablas x 2
        assert len(fks) - len(auditoria) == 12  # FK de dominio
        assert len(fks) == 34

    def test_todos_los_modelos_del_proyecto_estan_en_el_inventario(self) -> None:
        """Nadie ha anadido una entidad fuera del DER."""
        declarados = {spec["model"].lower() for spec in DER.values()}
        reales = {
            f"{m._meta.app_label}.{m._meta.model_name}"
            for m in apps.get_models()
            if m._meta.app_label
            in {"core", "people", "medications", "appointments", "massive_load"}
        }
        assert reales == declarados
