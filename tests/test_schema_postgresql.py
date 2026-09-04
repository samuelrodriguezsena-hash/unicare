"""Verificacion del esquema fisico realmente creado en PostgreSQL.

Es el ultimo eslabon de la cadena del contrato:

    DER  ->  modelos      (tests/test_der_contract.py)
          ->  migraciones (tests/test_migrations.py)
          ->  PostgreSQL  (este modulo)

Los otros dos no necesitan base de datos. Este SI: introspecciona
`information_schema` y `pg_catalog` sobre el esquema que `migrate` acaba de
crear, y lo compara contra el inventario del DER.

Si no hay PostgreSQL accesible, el modulo entero se salta en tiempo de
recoleccion, para que la suite siga siendo ejecutable sin infraestructura.
Levanta la base con:

    docker compose up -d db

ATENCION: que estos tests se salten NO es lo mismo que que pasen. Mientras
aparezcan como `skipped`, el esquema fisico no esta verificado.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.db import IntegrityError, connection
from django.db.models import ProtectedError
from django.utils import timezone

from tests.db import saltar_si_no_hay_postgresql
from tests.der_inventory import DER

saltar_si_no_hay_postgresql()

pytestmark = pytest.mark.django_db


def _consulta(sql: str, *params: object) -> list[tuple]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


class TestTablas:
    def test_existen_exactamente_las_tablas_del_der(self) -> None:
        filas = _consulta(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        )
        creadas = {fila[0] for fila in filas}
        # Django crea sus propias tablas de infraestructura; se descuentan.
        propias = creadas - {"django_migrations", "django_content_type"}
        propias = {t for t in propias if not t.startswith("auth_")}
        assert propias == set(DER)


@pytest.mark.parametrize("tabla", sorted(DER))
class TestColumnas:
    def test_las_columnas_y_su_nulabilidad_coinciden(self, tabla: str) -> None:
        filas = _consulta(
            """
            SELECT column_name, is_nullable FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = %s
            """,
            tabla,
        )
        real = {nombre: nullable == "YES" for nombre, nullable in filas}
        assert real == DER[tabla]["columns"]

    def test_la_clave_primaria_coincide(self, tabla: str) -> None:
        filas = _consulta(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                               AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = %s::regclass AND i.indisprimary
            """,
            f'"{tabla}"',
        )
        assert [fila[0] for fila in filas] == [DER[tabla]["pk"]]

    def test_las_claves_foraneas_apuntan_donde_dice_el_der(self, tabla: str) -> None:
        filas = _consulta(
            """
            SELECT kcu.column_name, ccu.table_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
              AND tc.table_name = %s
            """,
            tabla,
        )
        assert dict(filas) == DER[tabla]["foreign_keys"]


class TestRestriccionesUnicas:
    def test_las_columnas_unique_simples(self) -> None:
        for tabla, spec in DER.items():
            for columna in spec["unique"]:
                filas = _consulta(
                    """
                    SELECT COUNT(*)
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid
                                       AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = %s::regclass
                      AND i.indisunique
                      AND i.indnatts = 1
                      AND a.attname = %s
                    """,
                    f'"{tabla}"',
                    columna,
                )
                assert filas[0][0] >= 1, f"{tabla}.{columna} deberia ser UNIQUE"

    def test_uq_patient_pathology_existe_y_es_compuesta(self) -> None:
        filas = _consulta(
            """
            SELECT a.attname FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid
                               AND a.attnum = ANY(i.indkey)
            WHERE i.indexrelid = 'uq_patient_pathology'::regclass
            """
        )
        assert {fila[0] for fila in filas} == {"patient_id", "pathology_id"}

    def test_la_unica_patologia_principal_es_un_indice_parcial(self) -> None:
        """A-04: la regla "max 1 primary/patient" escrita en el propio DER."""
        filas = _consulta(
            """
            SELECT i.indisunique, pg_get_expr(i.indpred, i.indrelid)
            FROM pg_index i
            WHERE i.indexrelid = 'uq_patient_primary_pathology'::regclass
            """
        )
        es_unico, predicado = filas[0]
        assert es_unico
        assert predicado is not None, "Debe ser un indice PARCIAL, no total"
        assert "is_primary" in predicado


class TestCheckConstraints:
    ESPERADAS = {
        "ck_audit_log_action": "audit_log",
        "ck_clinical_history_entry_type": "clinical_history_entry",
        "ck_treatment_plan_status": "treatment_plan",
        "ck_appointment_status": "appointment",
        "ck_appointment_priority": "appointment",
        "ck_appointment_reminder_channel": "appointment_reminder",
        "ck_appointment_reminder_status": "appointment_reminder",
        "ck_import_batch_status": "import_batch",
        "ck_import_batch_row_status": "import_batch_row",
    }

    def test_los_enums_se_materializan_como_check_constraints(self) -> None:
        # DEC-10: dominio cerrado sin tipos ENUM nativos de PostgreSQL.
        filas = _consulta(
            r"""
            SELECT con.conname, cls.relname
            FROM pg_constraint con
            JOIN pg_class cls ON cls.oid = con.conrelid
            WHERE con.contype = 'c' AND con.conname LIKE 'ck\_%%'
            """
        )
        assert dict(filas) == self.ESPERADAS

    def test_no_se_creo_ningun_tipo_enum_nativo(self) -> None:
        filas = _consulta("SELECT COUNT(*) FROM pg_type WHERE typtype = 'e'")
        assert filas[0][0] == 0


class TestReglasDelDerEnLaBase:
    """Las restricciones del DER, ejercitadas de verdad contra PostgreSQL.

    Que el indice exista no prueba que se cumpla. Estos tests lo provocan.
    """

    @staticmethod
    def _paciente(identificacion: str):
        from apps.people.models import Patient

        return Patient.objects.create(
            identification_number=identificacion,
            first_name="Ana",
            last_name="Gomez",
        )

    def test_no_se_puede_repetir_la_misma_patologia_en_un_paciente(self) -> None:
        from apps.people.models import Pathology, PatientPathology

        paciente = self._paciente("uq-1")
        patologia = Pathology.objects.create(name="Carcinoma ductal")
        PatientPathology.objects.create(patient=paciente, pathology=patologia)

        with pytest.raises(IntegrityError):
            PatientPathology.objects.create(patient=paciente, pathology=patologia)

    def test_solo_una_patologia_principal_por_paciente(self) -> None:
        """A-04: la regla "max 1 primary/patient" escrita en el propio DER."""
        from apps.people.models import Pathology, PatientPathology

        paciente = self._paciente("uq-2")
        primera = Pathology.objects.create(name="Linfoma de Hodgkin")
        segunda = Pathology.objects.create(name="Melanoma")
        PatientPathology.objects.create(
            patient=paciente, pathology=primera, is_primary=True
        )

        with pytest.raises(IntegrityError):
            PatientPathology.objects.create(
                patient=paciente, pathology=segunda, is_primary=True
            )

    def test_si_pueden_coexistir_varias_patologias_no_principales(self) -> None:
        from apps.people.models import Pathology, PatientPathology

        paciente = self._paciente("uq-3")
        for nombre in ("Mieloma", "Sarcoma"):
            PatientPathology.objects.create(
                patient=paciente,
                pathology=Pathology.objects.create(name=nombre),
                is_primary=False,
            )
        assert paciente.pathologies.count() == 2

    def test_un_paciente_solo_tiene_un_historial_clinico(self) -> None:
        from apps.people.models import ClinicalHistory

        paciente = self._paciente("uq-4")
        ClinicalHistory.objects.create(patient=paciente)

        with pytest.raises(IntegrityError):
            ClinicalHistory.objects.create(patient=paciente)

    def test_el_check_rechaza_un_valor_fuera_del_enum(self) -> None:
        """DEC-10: el dominio cerrado se cumple en la base, no solo en Python."""
        from apps.people.models import ClinicalHistory, ClinicalHistoryEntry

        historial = ClinicalHistory.objects.create(patient=self._paciente("ck-1"))
        entrada = ClinicalHistoryEntry(
            clinical_history=historial,
            entry_date=date(2026, 1, 1),
            description="prueba",
            entry_type="VALOR_INVENTADO",
        )
        with pytest.raises(IntegrityError):
            entrada.save()

    def test_varios_pacientes_pueden_tener_identificacion_nula(self) -> None:
        """A-01: UNIQUE nullable. PostgreSQL admite multiples NULL."""
        from apps.people.models import Patient

        Patient.objects.create(first_name="Sin", last_name="Id")
        Patient.objects.create(first_name="Otro", last_name="Sin Id")
        assert Patient.objects.filter(identification_number__isnull=True).count() == 2

    def test_no_se_puede_borrar_un_paciente_con_citas(self) -> None:
        """DEC-04: PROTECT en las FK de dominio."""
        from apps.appointments.models import Appointment

        paciente = self._paciente("prot-1")
        Appointment.objects.create(
            patient=paciente, scheduled_at=timezone.now() + timedelta(days=1)
        )
        with pytest.raises(ProtectedError):
            paciente.delete()

    def test_borrar_una_cita_arrastra_sus_recordatorios(self) -> None:
        """DEC-04: CASCADE en las relaciones de composicion."""
        from apps.appointments.models import Appointment, AppointmentReminder

        cita = Appointment.objects.create(
            patient=self._paciente("casc-1"),
            scheduled_at=timezone.now() + timedelta(days=2),
        )
        AppointmentReminder.objects.create(
            appointment=cita, scheduled_at=timezone.now()
        )
        cita.delete()
        assert AppointmentReminder.objects.count() == 0


class TestTipos:
    def test_los_datetime_son_timestamptz(self) -> None:
        """DEC-12: USE_TZ. Los recordatorios dependen de ello."""
        filas = _consulta(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type LIKE 'timestamp%%'
              AND table_name = ANY(%s)
            """,
            list(DER),
        )
        sin_zona = [f for f in filas if f[2] != "timestamp with time zone"]
        assert sin_zona == []

    def test_los_valores_json_son_jsonb(self) -> None:
        filas = _consulta(
            """
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'audit_log'
              AND column_name IN ('old_values', 'new_values')
            """
        )
        assert {tipo for _, tipo in filas} == {"jsonb"}

    def test_los_varchar_sin_longitud_del_der_son_text(self) -> None:
        """DEC-01: no se inventa un limite que el DER no declara."""
        filas = _consulta(
            """
            SELECT table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND column_name IN ('identification_number', 'username', 'email')
            """
        )
        tipos = {(t, c): d for t, c, d in filas}
        assert tipos[("patient", "identification_number")] == "text"
        assert tipos[("user", "username")] == "text"
        assert tipos[("user", "email")] == "text"
        # En PATIENT el DER SI declara varchar(255).
        assert tipos[("patient", "email")] == "character varying"
