"""El contenedor de produccion (FASE 17).

El engine de Docker no esta disponible en el entorno de desarrollo de este
proyecto, asi que **la imagen nunca se ha construido aqui**. Eso no es excusa
para no verificar nada: casi todo lo que puede salir mal en un contenedor es
comprobable sin construirlo.

Lo que se ejercita de verdad, ejecutandolo:

  * la sonda de salud, contra un servidor HTTP real en loopback;
  * el reparto de roles del entrypoint, con `bash` y binarios de mentira;
  * el formato del log de acceso, con el propio formateador de gunicorn;
  * el comportamiento de las settings de produccion ante una sonda local,
    llamando a la aplicacion WSGI en un proceso aparte.

Lo que se comprueba leyendo los ficheros (Dockerfile, .dockerignore, compose):
propiedades que un build tampoco demostraria mejor, como que no haya secretos
o que el proceso no corra como root.

Lo unico que sigue sin verificarse es el build en si. Ver docs/DOCKER.md.
"""

from __future__ import annotations

import http.server
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

RAIZ = Path.cwd()
DOCKERFILE = (RAIZ / "Dockerfile").read_text(encoding="utf-8")
ENTRYPOINT = RAIZ / "scripts" / "entrypoint.sh"
COMPOSE_PROD = yaml.safe_load(
    (RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8")
)
SERVICIOS_DE_APP = ("web", "worker", "beat")


def _cargar_healthcheck():
    """Importa `scripts/healthcheck.py`, que no es un paquete."""
    ruta = RAIZ / "scripts" / "healthcheck.py"
    spec = importlib.util.spec_from_file_location("unicare_healthcheck", ruta)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# ---------------------------------------------------------------------------
# Sonda de salud
# ---------------------------------------------------------------------------
class _Manejador(http.server.BaseHTTPRequestHandler):
    """Devuelve el codigo que le pida el test."""

    codigo = 200
    destino = ""

    def do_GET(self) -> None:
        self.send_response(self.codigo)
        if self.destino:
            self.send_header("Location", self.destino)
        self.end_headers()
        self.wfile.write(b"{}")

    def log_message(self, *_args) -> None:
        """Sin ruido en la salida de los tests."""


@pytest.fixture
def servidor() -> Iterator:
    """Levanta un servidor HTTP real en loopback y devuelve su puerto."""

    def arrancar(codigo: int = 200, destino: str = "") -> int:
        _Manejador.codigo = codigo
        _Manejador.destino = destino
        httpd = http.server.HTTPServer(("127.0.0.1", 0), _Manejador)
        hilo = threading.Thread(target=httpd.serve_forever, daemon=True)
        hilo.start()
        creados.append(httpd)
        return httpd.server_address[1]

    creados: list = []
    yield arrancar
    for httpd in creados:
        httpd.shutdown()
        httpd.server_close()


class TestSondaDeSalud:
    """`scripts/healthcheck.py` es lo que decide si el contenedor esta sano."""

    @pytest.fixture(autouse=True)
    def _modulo(self, monkeypatch: pytest.MonkeyPatch):
        self.healthcheck = _cargar_healthcheck()
        monkeypatch.setattr(self.healthcheck, "HOST", "127.0.0.1")
        monkeypatch.setattr(self.healthcheck, "PATH", "/api/v1/health/")
        monkeypatch.setattr(self.healthcheck, "TIMEOUT", 5.0)

    def test_un_200_es_un_contenedor_sano(self, servidor, monkeypatch) -> None:
        monkeypatch.setattr(self.healthcheck, "PORT", str(servidor(200)))
        assert self.healthcheck.comprobar() == 0

    def test_un_503_no_lo_es(self, servidor, monkeypatch) -> None:
        monkeypatch.setattr(self.healthcheck, "PORT", str(servidor(503)))
        assert self.healthcheck.comprobar() == 1

    def test_un_redirect_no_cuenta_como_salud(self, servidor, monkeypatch) -> None:
        """El motivo por el que esta sonda no es `curl -fsS`.

        En produccion `SECURE_SSL_REDIRECT` esta activo, asi que una sonda mal
        planteada recibe un 301 hacia https. `curl -f` no falla ante un 3xx:
        daria el contenedor por sano sin que la peticion haya llegado nunca a
        la vista. Aqui el redirect se sigue, no se aprueba: si el destino no
        responde, la sonda falla.
        """
        puerto = servidor(301, destino="https://127.0.0.1:1/api/v1/health/")
        monkeypatch.setattr(self.healthcheck, "PORT", str(puerto))
        assert self.healthcheck.comprobar() == 1

    def test_sin_nadie_escuchando_falla(self, monkeypatch) -> None:
        with socket.socket() as libre:
            libre.bind(("127.0.0.1", 0))
            puerto = libre.getsockname()[1]
        monkeypatch.setattr(self.healthcheck, "PORT", str(puerto))
        assert self.healthcheck.comprobar() == 1

    def test_los_parametros_se_leen_del_entorno(self) -> None:
        """En un orquestador la sonda puede tener que apuntar a la readiness."""
        modulo = _cargar_healthcheck()
        assert modulo.PATH == "/api/v1/health/"  # liveness por defecto
        assert modulo.PORT == os.environ.get("PORT", "8000")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
BASH = shutil.which("bash")

sin_bash = pytest.mark.skipif(
    BASH is None, reason="Se necesita bash para ejecutar el entrypoint"
)


def _ejecutar_entrypoint(tmp_path: Path, *argumentos: str, entorno=None):
    """Ejecuta el entrypoint con binarios de mentira en el PATH.

    Ni gunicorn ni celery llegan a arrancar: cada uno se sustituye por un
    script que imprime como lo han invocado. Asi se comprueba el reparto de
    roles de verdad, sin contenedor.
    """
    bin_falso = tmp_path / "bin"
    bin_falso.mkdir(exist_ok=True)
    for nombre in ("gunicorn", "celery", "python"):
        script = bin_falso / nombre
        script.write_text(
            f'#!/usr/bin/env bash\necho "{nombre} $*"\n', encoding="utf-8"
        )
        script.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{bin_falso}{os.pathsep}{os.environ['PATH']}",
        **(entorno or {}),
    }
    return subprocess.run(  # noqa: S603 - rutas construidas por el propio test
        [str(BASH), str(ENTRYPOINT), *argumentos],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


@sin_bash
class TestEntrypoint:
    """Un unico entrypoint reparte tres roles. Si se equivoca, no arranca nada."""

    def test_web_arranca_gunicorn(self, tmp_path: Path) -> None:
        resultado = _ejecutar_entrypoint(tmp_path, "web")
        assert resultado.returncode == 0, resultado.stderr
        assert "gunicorn config.wsgi:application" in resultado.stdout
        assert "--bind 0.0.0.0:8000" in resultado.stdout

    def test_web_no_recoge_estaticos_por_defecto(self, tmp_path: Path) -> None:
        """En produccion la API responde solo JSON: no hay estaticos que servir."""
        resultado = _ejecutar_entrypoint(tmp_path, "web")
        assert "collectstatic" not in resultado.stdout

    def test_collect_static_se_puede_reactivar(self, tmp_path: Path) -> None:
        resultado = _ejecutar_entrypoint(
            tmp_path, "web", entorno={"COLLECT_STATIC": "1"}
        )
        assert "manage.py collectstatic --noinput" in resultado.stdout

    def test_el_puerto_es_configurable(self, tmp_path: Path) -> None:
        resultado = _ejecutar_entrypoint(tmp_path, "web", entorno={"PORT": "9001"})
        assert "--bind 0.0.0.0:9001" in resultado.stdout

    def test_worker_arranca_un_worker_de_celery(self, tmp_path: Path) -> None:
        resultado = _ejecutar_entrypoint(tmp_path, "worker")
        assert "celery -A config worker" in resultado.stdout

    def test_beat_arranca_el_planificador(self, tmp_path: Path) -> None:
        resultado = _ejecutar_entrypoint(tmp_path, "beat")
        assert "celery -A config beat" in resultado.stdout

    def test_migrate_es_un_rol_explicito(self, tmp_path: Path) -> None:
        """Las migraciones son un paso del despliegue, nunca algo automatico."""
        resultado = _ejecutar_entrypoint(tmp_path, "migrate")
        assert "manage.py migrate --noinput" in resultado.stdout

    def test_las_migraciones_no_se_ejecutan_al_arrancar_web(
        self, tmp_path: Path
    ) -> None:
        resultado = _ejecutar_entrypoint(tmp_path, "web")
        assert "migrate" not in resultado.stdout

    def test_un_comando_cualquiera_se_ejecuta_tal_cual(self, tmp_path: Path) -> None:
        """`docker compose run --rm web python manage.py shell` debe funcionar."""
        resultado = _ejecutar_entrypoint(tmp_path, "python", "manage.py", "shell")
        assert "python manage.py shell" in resultado.stdout


def _gunicorn_importable() -> bool:
    """gunicorn solo se importa en POSIX (fcntl, grp, pwd)."""
    try:
        import gunicorn.glogging  # noqa: F401
    except ModuleNotFoundError:
        return False
    return True


@sin_bash
class TestLogDeAcceso:
    """El log de acceso no puede registrar datos clinicos.

    `?search=Juan+Perez` en una busqueda de pacientes acabaria escrito en el log
    de cada peticion. El formato por defecto de gunicorn (`%(r)s`) construye la
    linea con `RAW_URI`, que incluye la query; el del entrypoint usa `%(U)s`,
    que es solo `PATH_INFO`.
    """

    # Los dos unicos atomos de gunicorn que arrastran la query string.
    ATOMOS_CON_QUERY = {"r", "q"}

    def _formato(self, tmp_path: Path) -> str:
        resultado = _ejecutar_entrypoint(tmp_path, "web")
        marca = "--access-logformat "
        trozo = resultado.stdout[resultado.stdout.index(marca) + len(marca) :]
        return trozo.split(" --access-logfile")[0]

    def test_el_formato_no_usa_ningun_atomo_con_query_string(
        self, tmp_path: Path
    ) -> None:
        formato = self._formato(tmp_path)
        usados = set(re.findall(r"%\((\w+)\)", formato))
        assert usados & self.ATOMOS_CON_QUERY == set()
        assert "U" in usados  # la ruta si se registra: es lo util

    @pytest.mark.skipif(
        not _gunicorn_importable(), reason="gunicorn no se importa en Windows"
    )
    def test_el_formateador_de_gunicorn_no_escribe_la_query(
        self, tmp_path: Path
    ) -> None:
        """Lo anterior, comprobado con el formateador real y no con la cadena."""
        from datetime import timedelta

        from gunicorn.config import Config
        from gunicorn.glogging import Logger

        config = Config()
        config.set("accesslog", "-")
        config.set("access_log_format", self._formato(tmp_path))

        environ = {
            "REMOTE_ADDR": "10.0.0.1",
            "REQUEST_METHOD": "GET",
            "PATH_INFO": "/api/v1/patients/",
            "QUERY_STRING": "search=Juan+Perez",
            "RAW_URI": "/api/v1/patients/?search=Juan+Perez",
            "SERVER_PROTOCOL": "HTTP/1.1",
        }
        respuesta = type("R", (), {"status": "200 OK", "sent": 120, "headers": []})()
        linea = config.access_log_format % Logger(config).atoms(
            respuesta, [], environ, timedelta(seconds=0, microseconds=1000)
        )

        assert "Juan" not in linea
        assert "search" not in linea
        assert "/api/v1/patients/" in linea


# ---------------------------------------------------------------------------
# Imagen
# ---------------------------------------------------------------------------
class TestImagen:
    def test_el_proceso_no_corre_como_root(self) -> None:
        assert "USER unicare" in DOCKERFILE
        assert DOCKERFILE.index("USER unicare") < DOCKERFILE.index("ENTRYPOINT")

    def test_es_multi_stage(self) -> None:
        """Las herramientas de compilacion no viajan a la imagen final."""
        assert DOCKERFILE.count("FROM python:3.12-slim") == 2
        assert "build-essential" in DOCKERFILE.split("AS runtime")[0]
        assert "build-essential" not in DOCKERFILE.split("AS runtime")[1]

    def test_la_sonda_de_salud_es_el_script_del_proyecto(self) -> None:
        instrucciones = "\n".join(
            linea
            for linea in DOCKERFILE.splitlines()
            if not linea.lstrip().startswith("#")
        )
        assert "/app/scripts/healthcheck.py" in instrucciones
        # curl era el unico motivo para instalar un paquete de sistema extra.
        assert "curl" not in instrucciones

    def test_no_hay_secretos_en_la_imagen(self) -> None:
        """Regla absoluta del proyecto: cero secretos en el repositorio."""
        prohibidos = ("SECRET_KEY=", "API_KEY=", "PASSWORD=", "SENTRY_DSN=", "TOKEN=")
        for aguja in prohibidos:
            assert aguja not in DOCKERFILE, aguja

    def test_las_settings_por_defecto_son_las_de_produccion(self) -> None:
        assert "DJANGO_SETTINGS_MODULE=config.settings.production" in DOCKERFILE


class TestDockerignore:
    """Un `.env.production` horneado en la imagen son credenciales publicadas."""

    PATRONES = (RAIZ / ".dockerignore").read_text(encoding="utf-8")

    def _excluido(self, nombre: str) -> bool:
        import fnmatch

        excluido = False
        for linea in self.PATRONES.splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#"):
                continue
            negado = linea.startswith("!")
            patron = linea[1:] if negado else linea
            if fnmatch.fnmatch(nombre, patron):
                excluido = not negado
        return excluido

    @pytest.mark.parametrize(
        "fichero", [".env", ".env.production", ".env.local", ".coverage"]
    )
    def test_no_entran_en_la_imagen(self, fichero: str) -> None:
        assert self._excluido(fichero)

    def test_la_plantilla_si_entra(self) -> None:
        """`.env.example` no tiene valores reales y documenta el contrato."""
        assert not self._excluido(".env.example")

    def test_cubre_cualquier_sufijo(self) -> None:
        """`.env` a secas no cubria `.env.production`. Es el fallo tipico."""
        assert ".env.*" in self.PATRONES


# ---------------------------------------------------------------------------
# Compose de produccion
# ---------------------------------------------------------------------------
class TestComposeDeProduccion:
    def test_los_tres_procesos_estan_definidos(self) -> None:
        for servicio in SERVICIOS_DE_APP:
            assert servicio in COMPOSE_PROD["services"]

    def test_no_se_monta_el_codigo(self) -> None:
        """La imagen es inmutable: corre lo que se construyo y se probo.

        Un bind mount del directorio de trabajo, como el de desarrollo, haria
        que el contenedor ejecutase lo que hubiera en el disco del servidor.
        """
        for servicio in SERVICIOS_DE_APP:
            for volumen in COMPOSE_PROD["services"][servicio].get("volumes", []):
                origen = volumen.split(":")[0] if isinstance(volumen, str) else ""
                assert not origen.startswith("."), f"{servicio} monta {volumen}"

    def test_solo_web_publica_puertos_y_solo_en_loopback(self) -> None:
        """Delante va un proxy inverso: gunicorn no habla TLS."""
        for nombre, servicio in COMPOSE_PROD["services"].items():
            puertos = servicio.get("ports", [])
            if nombre != "web":
                assert not puertos, f"{nombre} publica {puertos}"
                continue
            for puerto in puertos:
                assert str(puerto).startswith("127.0.0.1:"), puerto

    def test_todos_los_procesos_usan_las_settings_de_produccion(self) -> None:
        for servicio in SERVICIOS_DE_APP:
            entorno = COMPOSE_PROD["services"][servicio]["environment"]
            assert entorno["DJANGO_SETTINGS_MODULE"] == "config.settings.production"

    def test_todo_se_reinicia_solo(self) -> None:
        for nombre, servicio in COMPOSE_PROD["services"].items():
            if "profiles" in servicio:
                continue
            assert servicio["restart"] == "unless-stopped", nombre

    def test_los_logs_estan_acotados(self) -> None:
        """Sin `max-size` un contenedor de larga vida llena el disco del host."""
        for nombre, servicio in COMPOSE_PROD["services"].items():
            assert servicio["logging"]["options"]["max-size"], nombre

    def test_beat_conserva_su_estado_en_un_volumen(self) -> None:
        """Si el fichero se pierde, beat vuelve a disparar el despacho."""
        beat = COMPOSE_PROD["services"]["beat"]
        destino = beat["environment"]["CELERY_BEAT_SCHEDULE_FILENAME"]
        montajes = [v.split(":")[1] for v in beat["volumes"]]
        assert any(destino.startswith(m) for m in montajes)

    def test_ninguna_credencial_esta_escrita_en_el_fichero(self) -> None:
        crudo = (RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8")
        for entorno in (
            s.get("environment", {}) for s in COMPOSE_PROD["services"].values()
        ):
            for clave, valor in entorno.items():
                if any(x in clave for x in ("PASSWORD", "SECRET", "KEY", "DSN")):
                    assert valor.startswith("${"), f"{clave} lleva un valor literal"
        assert "env_file" in crudo

    def test_la_base_de_datos_local_es_opcional(self) -> None:
        """Por defecto PostgreSQL es externo: backups y upgrades no son de aqui."""
        assert COMPOSE_PROD["services"]["db"]["profiles"] == ["db-local"]

    def test_no_arranca_migraciones_automaticas(self) -> None:
        crudo = (RAIZ / "docker-compose.prod.yml").read_text(encoding="utf-8")
        for servicio in SERVICIOS_DE_APP:
            assert COMPOSE_PROD["services"][servicio]["command"] != ["migrate"]
        assert "run --rm web migrate" in crudo  # documentado como paso explicito


# ---------------------------------------------------------------------------
# Comportamiento real de las settings de produccion ante una sonda
# ---------------------------------------------------------------------------
_PROBE = """
import io, json, os, sys
sys.path.insert(0, os.getcwd())
from config.wsgi import application

def peticion(path, host, headers=None):
    environ = {
        "REQUEST_METHOD": "GET", "PATH_INFO": path,
        "SERVER_NAME": "localhost", "SERVER_PORT": "8000",
        "SERVER_PROTOCOL": "HTTP/1.1", "HTTP_HOST": host,
        "wsgi.input": io.BytesIO(b""), "wsgi.errors": io.StringIO(),
        "wsgi.url_scheme": "http", "wsgi.multithread": False,
        "wsgi.multiprocess": False, "wsgi.run_once": False,
    }
    environ.update(headers or {})
    capturado = {}
    def start_response(status, cabeceras, exc_info=None):
        capturado["status"] = int(status.split()[0])
        capturado["headers"] = dict(cabeceras)
    cuerpo = b"".join(application(environ, start_response))
    return capturado["status"], capturado["headers"], cuerpo.decode("utf-8", "replace")

from django.conf import settings
salida = {}
for nombre, args in {
    "sonda_local": ("/api/v1/health/", "localhost:8000"),
    "sonda_ip": ("/api/v1/health/", "127.0.0.1:8000"),
    "ruta_normal": ("/api/v1/patients/", "unicare.example.com"),
}.items():
    estado, cabeceras, cuerpo = peticion(*args)
    salida[nombre] = [estado, cabeceras.get("Location", ""), cuerpo[:60]]
salida["renderers"] = list(settings.REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"])
print("RESULTADO" + json.dumps(salida))
"""


@pytest.fixture(scope="module")
def sondas_en_produccion() -> dict:
    """Llama a la aplicacion WSGI con las settings de produccion cargadas.

    Es la unica forma de comprobar esto: la suite corre con `testing`, donde no
    hay ni redirect a HTTPS ni ALLOWED_HOSTS restrictivo. Un proceso aparte
    porque las settings se resuelven al importar.
    """
    entorno = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "config.settings.production",
        "DJANGO_SECRET_KEY": "clave-de-prueba-no-secreta",
        "DJANGO_ALLOWED_HOSTS": "unicare.example.com",
        "DATABASE_URL": "postgres://u:p@db:5432/d",
        "REDIS_URL": "redis://r:6379/0",
        "FARMACOS_API_BASE_URL": "https://farmacos.invalid",
        "SENTRY_DSN": "",
    }
    resultado = subprocess.run(  # noqa: S603 - codigo literal, sin entrada externa
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
        timeout=180,
        env=entorno,
        cwd=RAIZ,
    )
    assert resultado.returncode == 0, resultado.stderr[-2000:]
    linea = next(
        line for line in resultado.stdout.splitlines() if line.startswith("RESULTADO")
    )
    return json.loads(linea[len("RESULTADO") :])


class TestSettingsDeProduccionAnteUnaSonda:
    """El HEALTHCHECK del contenedor tiene que recibir un 200 de verdad.

    Las dos cosas que comprueban estos tests estaban rotas y se detectaron
    ejecutando esto, no leyendo el codigo:

      * con `Host: localhost` Django respondia 400 (DisallowedHost), asi que el
        contenedor quedaba unhealthy para siempre aunque estuviera sano;
      * sobre HTTP plano la respuesta era un 301 hacia https, que las sondas dan
        por bueno sin haber llegado nunca a la vista.
    """

    def test_la_sonda_local_recibe_un_200(self, sondas_en_produccion: dict) -> None:
        estado, _location, cuerpo = sondas_en_produccion["sonda_local"]
        assert estado == 200
        assert "ok" in cuerpo

    def test_tambien_por_ip(self, sondas_en_produccion: dict) -> None:
        estado, _location, _cuerpo = sondas_en_produccion["sonda_ip"]
        assert estado == 200

    def test_el_resto_de_la_api_sigue_redirigiendo_a_https(
        self, sondas_en_produccion: dict
    ) -> None:
        """La exencion es solo para los health checks, no un apagon del redirect."""
        estado, location, _cuerpo = sondas_en_produccion["ruta_normal"]
        assert estado == 301
        assert location.startswith("https://")

    def test_la_api_responde_solo_json(self, sondas_en_produccion: dict) -> None:
        """El navegador de DRF es una herramienta de desarrollo."""
        assert sondas_en_produccion["renderers"] == [
            "rest_framework.renderers.JSONRenderer"
        ]


# ---------------------------------------------------------------------------
# El propio pipeline
# ---------------------------------------------------------------------------
class TestPasoDeCheckDeploy:
    """El paso `check --deploy` del pipeline, ejecutado con SUS valores.

    Este test existe porque el pipeline estaba roto: la clave de ejemplo del
    workflow tenia 35 caracteres, `check --deploy` emite W009 por debajo de 50 y
    el paso corre con `--fail-level WARNING`. El job habria fallado en su primera
    ejecucion, y como el proyecto todavia no es un repositorio git, nadie lo
    habria visto hasta entonces.

    Leer el entorno del propio workflow, en vez de reescribirlo aqui, es lo que
    hace que el test siga valiendo cuando alguien lo cambie.
    """

    @staticmethod
    def _entorno_del_workflow() -> dict:
        workflow = yaml.safe_load(
            (RAIZ / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        )
        pasos = workflow["jobs"]["configuracion-de-produccion"]["steps"]
        paso = next(p for p in pasos if p.get("name") == "check --deploy")
        return {clave: str(valor) for clave, valor in paso["env"].items()}

    def test_el_entorno_del_workflow_pasa_el_check(self) -> None:
        resultado = subprocess.run(  # noqa: S603 - argumentos literales
            [
                sys.executable,
                "manage.py",
                "check",
                "--deploy",
                "--fail-level",
                "WARNING",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, **self._entorno_del_workflow()},
            cwd=RAIZ,
        )
        assert resultado.returncode == 0, resultado.stdout + resultado.stderr

    def test_la_clave_de_ejemplo_supera_el_umbral_de_django(self) -> None:
        """W009 exige 50 caracteres. No es un secreto, pero tiene que ser larga."""
        assert len(self._entorno_del_workflow()["DJANGO_SECRET_KEY"]) >= 50
