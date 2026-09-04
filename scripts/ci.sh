#!/usr/bin/env bash
# Los mismos pasos que ejecuta el pipeline, en local.
#
# Sirve para dos cosas: no descubrir en CI algo que se podia haber visto antes
# de subir, y poder verificar el propio pipeline sin depender de GitHub.
#
#   scripts/ci.sh              todo salvo el build de la imagen
#   scripts/ci.sh --con-docker incluye el build
#
# Requiere PostgreSQL accesible via DATABASE_URL. Ver docs/TESTING.md.
set -euo pipefail

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.testing}"

CON_DOCKER=0
[ "${1:-}" = "--con-docker" ] && CON_DOCKER=1

# Usa el interprete del venv si existe; si no, el que este en PATH.
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python"
fi

fallos=0
paso() {
  local titulo="$1"
  shift
  printf '\n\033[1m==> %s\033[0m\n' "${titulo}"
  if "$@"; then
    printf '    OK\n'
  else
    printf '    FALLO\n'
    fallos=$((fallos + 1))
  fi
}

paso "Formato (black)" "${PY}" -m black --check --diff .
paso "Lint (ruff)" "${PY}" -m ruff check .
paso "Lint (flake8)" "${PY}" -m flake8 .
paso "Comprobaciones de Django" "${PY}" manage.py check
paso "Migraciones sincronizadas" "${PY}" manage.py makemigrations --check --dry-run
paso "Tests y cobertura" "${PY}" -m pytest --cov --cov-report=term-missing
paso "Gate de cobertura (85 %)" "${PY}" -m coverage report --fail-under=85

# `docker compose config` no necesita el daemon: solo lee y resuelve el fichero.
#
# El fichero declara `env_file: .env.production`, asi que tiene que existir. Si
# ya hay uno real se usa tal cual y no se toca; si no, se crea uno de mentira y
# se borra al terminar.
validar_compose() {
  local propio=0
  if [ ! -f .env.production ]; then
    propio=1
    cat > .env.production <<'ENV'
DJANGO_SECRET_KEY=clave-de-pruebas-sin-ningun-valor-real-0123456789abcdef-unicare
DJANGO_ALLOWED_HOSTS=example.com
DATABASE_URL=postgres://u:p@db:5432/d
REDIS_URL=redis://redis:6379/0
FARMACOS_API_BASE_URL=https://farmacos.invalid
POSTGRES_USER=unicare
POSTGRES_PASSWORD=solo-local
POSTGRES_DB=unicare
ENV
  fi

  local resultado=0
  docker compose --env-file .env.production -f docker-compose.prod.yml \
    --profile db-local config --quiet || resultado=1
  if [ "${propio}" = "1" ]; then
    rm -f .env.production
  fi
  return "${resultado}"
}

if command -v docker >/dev/null 2>&1; then
  paso "Compose de produccion" validar_compose
else
  printf '\n\033[1m==> Compose de produccion\033[0m\n    omitido (no hay docker)\n'
fi

if [ "${CON_DOCKER}" = "1" ]; then
  paso "Build de la imagen" docker build -t unicare:ci .
else
  printf '\n\033[1m==> Build de la imagen\033[0m\n    omitido (usa --con-docker)\n'
fi

printf '\n'
if [ "${fallos}" -eq 0 ]; then
  printf '\033[1mTodo correcto.\033[0m\n'
else
  printf '\033[1m%s paso(s) han fallado.\033[0m\n' "${fallos}"
fi
exit "${fallos}"
