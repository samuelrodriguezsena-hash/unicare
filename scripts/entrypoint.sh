#!/usr/bin/env bash
# Entrypoint unico para los tres roles del contenedor: web, worker y beat.
# Las migraciones NO se ejecutan automaticamente: son un paso explicito y
# auditable del deployment (ver docs/DEPLOYMENT.md).
#
# El formato del log de acceso omite deliberadamente la query string: este
# sistema maneja informacion clinica y `?search=Juan+Perez` acabaria escrito
# en el log de cada peticion. El formato por defecto de gunicorn si la
# incluye, porque registra la linea de peticion completa.
set -euo pipefail

ROLE="${1:-web}"

case "${ROLE}" in
  web)
    # Por defecto NO se recogen estaticos: en produccion la API responde
    # solo JSON y no queda nada que servir (ver config/settings/production).
    # COLLECT_STATIC=1 lo reactiva si se vuelve a habilitar el navegador DRF.
    if [ "${COLLECT_STATIC:-0}" = "1" ]; then
      python manage.py collectstatic --noinput
    fi
    exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT:-8000}" \
      --workers "${GUNICORN_WORKERS:-3}" \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --access-logformat "${GUNICORN_ACCESS_LOG_FORMAT:-%(h)s \"%(m)s %(U)s\" %(s)s %(b)s %(L)s}" \
      --access-logfile - \
      --error-logfile -
    ;;
  worker)
    exec celery -A config worker \
      --loglevel "${CELERY_LOG_LEVEL:-info}" \
      --concurrency "${CELERY_CONCURRENCY:-2}"
    ;;
  beat)
    exec celery -A config beat --loglevel "${CELERY_LOG_LEVEL:-info}"
    ;;
  migrate)
    exec python manage.py migrate --noinput
    ;;
  *)
    exec "$@"
    ;;
esac
