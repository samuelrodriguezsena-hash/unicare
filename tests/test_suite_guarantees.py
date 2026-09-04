"""Garantias de la suite (FASE 15).

No prueban una funcionalidad concreta, sino propiedades del proyecto que
ninguna otra cosa comprueba:

  * el gate de cobertura del 85 % funciona de verdad;
  * ningun test puede salir a la red;
  * los modulos de settings de development y production son importables;
  * las factories construyen objetos validos contra el DER;
  * cada app de dominio tiene tests.

Varias se apoyan en subprocesos: es la unica forma de comprobar cosas que en
este proceso ya estan resueltas (settings cargadas, modulos importados).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import RedProhibidaError, _connect_vigilado
from tests.db import skipif_sin_postgresql

APPS_DE_DOMINIO = ("core", "people", "medications", "appointments", "massive_load")


def _ejecutar(
    *argumentos: str, entorno: dict | None = None
) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **(entorno or {})}
    return subprocess.run(  # noqa: S603 - argumentos literales, sin entrada externa
        [sys.executable, *argumentos],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
        cwd=Path.cwd(),
    )


class TestGateDeCobertura:
    """El 85 % es un GATE obligatorio del proyecto."""

    def test_esta_configurado_al_85(self) -> None:
        import tomllib

        with Path("pyproject.toml").open("rb") as fichero:
            config = tomllib.load(fichero)
        assert config["tool"]["coverage"]["report"]["fail_under"] == 85

    def test_el_gate_bloquea_una_cobertura_insuficiente(self, tmp_path: Path) -> None:
        """Un umbral configurado que no bloquea nada no es un gate.

        Se mide un subconjunto minimo de la suite en un fichero de datos
        aparte: cubre muy poco del proyecto, asi que el gate del 85 % DEBE
        rechazarlo con codigo 2. Sobre los datos reales no se podria probar,
        porque la cobertura del proyecto es del 100 %.
        """
        datos = str(tmp_path / "cobertura")

        medicion = _ejecutar(
            "-m",
            "coverage",
            "run",
            "--source=apps",
            "-m",
            "pytest",
            "tests/test_core_validators.py",
            "-q",
            "--no-cov",
            entorno={"COVERAGE_FILE": datos},
        )
        assert medicion.returncode == 0, medicion.stdout[-1500:]

        insuficiente = _ejecutar(
            "-m",
            "coverage",
            "report",
            "--fail-under=85",
            entorno={"COVERAGE_FILE": datos},
        )
        assert insuficiente.returncode == 2, insuficiente.stdout[-800:]

        # Y el mismo mecanismo devuelve 0 cuando el umbral si se alcanza.
        suficiente = _ejecutar(
            "-m",
            "coverage",
            "report",
            "--fail-under=1",
            entorno={"COVERAGE_FILE": datos},
        )
        assert suficiente.returncode == 0


class TestAislamientoDeRed:
    """Requisito explicito: los tests no hacen llamadas reales."""

    def test_la_salvaguarda_esta_activa(self) -> None:
        import socket

        assert socket.socket.connect is _connect_vigilado

    def test_bloquea_una_conexion_saliente(self) -> None:
        import socket

        with pytest.raises(RedProhibidaError) as exc:
            socket.socket().connect(("api.example.com", 443))
        assert "no puede salir a la red" in str(exc.value)

    @skipif_sin_postgresql()
    @pytest.mark.django_db
    def test_permite_loopback(self) -> None:
        # PostgreSQL y los servicios locales tienen que seguir funcionando.
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            assert cursor.fetchone() == (1,)

    def test_las_integraciones_externas_se_mockean(self) -> None:
        """Las dos integraciones tienen dobles en la suite."""
        contenido = "\n".join(
            fichero.read_text(encoding="utf-8")
            for fichero in Path("tests").glob("test_*.py")
        )
        assert "respx" in contenido  # API de farmacos
        assert "GeminiFalso" in contenido  # SDK de Gemini


class TestModulosDeSettings:
    """`development` y `production` no se cargan durante los tests.

    Un error de sintaxis o una variable mal referenciada en ellos no lo
    detectaria nada hasta el despliegue. Se importan en un proceso aparte.
    """

    COMUNES = {
        "DJANGO_SECRET_KEY": "clave-de-prueba-no-secreta",
        "DJANGO_ALLOWED_HOSTS": "example.com",
        "DATABASE_URL": "postgres://u:p@db:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "FARMACOS_API_BASE_URL": "https://farmacos.invalid",
    }

    @pytest.mark.parametrize("modulo", ["development", "production"])
    def test_se_importan_sin_error(self, modulo: str) -> None:
        resultado = _ejecutar(
            "-c",
            "import django; django.setup(); "
            "from django.conf import settings; print(settings.DEBUG)",
            entorno={
                **self.COMUNES,
                "DJANGO_SETTINGS_MODULE": f"config.settings.{modulo}",
                "SENTRY_DSN": "",
            },
        )
        assert resultado.returncode == 0, resultado.stderr[-1500:]

    def test_produccion_desactiva_debug(self) -> None:
        resultado = _ejecutar(
            "-c",
            "import django; django.setup(); "
            "from django.conf import settings; print(settings.DEBUG)",
            entorno={
                **self.COMUNES,
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "SENTRY_DSN": "",
            },
        )
        assert resultado.stdout.strip() == "False"

    def test_produccion_exige_allowed_hosts(self) -> None:
        """Una cadena vacia dejaria ALLOWED_HOSTS=[] y un 400 en cada peticion.

        Es preferible fallar al arrancar que desplegar algo que rechaza todo.
        """
        entorno = {
            **self.COMUNES,
            "DJANGO_SETTINGS_MODULE": "config.settings.production",
            "DJANGO_ALLOWED_HOSTS": "",
            "SENTRY_DSN": "",
        }
        resultado = _ejecutar("-c", "import django; django.setup()", entorno=entorno)
        assert resultado.returncode != 0
        assert "DJANGO_ALLOWED_HOSTS" in resultado.stderr

    def test_produccion_arranca_con_sentry(self) -> None:
        resultado = _ejecutar(
            "-c",
            "import django; django.setup(); print('ok')",
            entorno={
                **self.COMUNES,
                "DJANGO_SETTINGS_MODULE": "config.settings.production",
                "SENTRY_DSN": "https://clave@o0.ingest.sentry.io/0",
            },
        )
        assert resultado.returncode == 0, resultado.stderr[-1500:]
        assert "ok" in resultado.stdout


class TestCoberturaPorApp:
    def test_cada_app_de_dominio_tiene_tests(self) -> None:
        contenido = "\n".join(
            fichero.read_text(encoding="utf-8")
            for fichero in Path("tests").glob("test_*.py")
        )
        for app in APPS_DE_DOMINIO:
            assert f"apps.{app}" in contenido, f"La app {app} no aparece en los tests"

    def test_hay_tests_de_cada_area_que_exige_la_documentacion(self) -> None:
        esperados = {
            "test_der_contract.py",  # modelos y relaciones
            "test_migrations.py",  # migraciones
            "test_schema_postgresql.py",  # esquema fisico
            "test_people_api.py",  # CRUD, busqueda, filtros, historial
            "test_treatment_plans.py",  # tratamientos
            "test_appointments_api.py",  # citas
            "test_reminders.py",  # recordatorios y Celery
            "test_massive_load.py",  # importaciones
            "test_farmacos_api.py",  # integracion externa
            "test_gemini_service.py",  # integracion IA
            "test_audit.py",  # auditoria
            "test_jwt_auth.py",  # seguridad
            "test_permissions_coverage.py",  # permisos
            "test_observability.py",  # Sentry
        }
        existentes = {fichero.name for fichero in Path("tests").glob("test_*.py")}
        assert esperados <= existentes


@skipif_sin_postgresql()
@pytest.mark.django_db
class TestFactories:
    """Las factories deben producir objetos validos contra el DER.

    El `skipif` se evalua en RECOLECCION, no dentro del test: la fixture `db`
    de pytest-django se resuelve antes del cuerpo, y si no puede crear la base
    Django pregunta por stdin si desea borrarla, con lo que la suite se queda
    colgada en lugar de saltarse.
    """

    def test_construyen_sin_violar_restricciones(self) -> None:
        from tests import factories

        creadas = [
            factories.UserFactory,
            factories.PatientFactory,
            factories.PathologyFactory,
            factories.PatientPathologyFactory,
            factories.ClinicalHistoryFactory,
            factories.ClinicalHistoryEntryFactory,
            factories.NoteFactory,
            factories.TreatmentPlanFactory,
            factories.TreatmentPlanMedicationFactory,
            factories.AppointmentFactory,
            factories.AppointmentReminderFactory,
            factories.ImportBatchFactory,
            factories.ImportBatchRowFactory,
        ]
        for fabrica in creadas:
            assert fabrica().pk is not None

    def test_las_secuencias_respetan_las_restricciones_unique(self) -> None:
        from tests.factories import PathologyFactory, PatientFactory

        pacientes = PatientFactory.create_batch(5)
        identificaciones = {p.identification_number for p in pacientes}
        assert len(identificaciones) == 5

        patologias = PathologyFactory.create_batch(5)
        assert len({p.name for p in patologias}) == 5

    def test_el_historial_respeta_el_1_a_1_del_der(self) -> None:
        from tests.factories import ClinicalHistoryFactory, PatientFactory

        paciente = PatientFactory()
        primero = ClinicalHistoryFactory(patient=paciente)
        segundo = ClinicalHistoryFactory(patient=paciente)

        # `django_get_or_create` evita violar UNIQUE(patient_id).
        assert primero.pk == segundo.pk
