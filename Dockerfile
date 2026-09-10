# UniCare - imagen de produccion.
# Multi-stage, usuario no root, sin secretos. DEC-13: python:3.12-slim.

# ---------------------------------------------------------------------------
# Stage 1: dependencias
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME=/opt/poetry \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_NO_INTERACTION=1

WORKDIR /build

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --upgrade pip \
    && pip install "poetry==${POETRY_VERSION}"

COPY pyproject.toml ./
COPY requirements/ requirements/
ARG REQUIREMENTS=requirements/production.txt
RUN if poetry check >/dev/null 2>&1; then \
        poetry install --only main --no-root --no-interaction; \
    else \
        python -m venv /opt/venv \
        && /opt/venv/bin/pip install --upgrade pip \
        && /opt/venv/bin/pip install -r ${REQUIREMENTS}; \
    fi

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    DJANGO_SETTINGS_MODULE=config.settings.production

# Solo libpq5: la sonda de salud es un script de la stdlib
# (scripts/healthcheck.py), asi que curl deja de ser necesario.
RUN apt-get update \
    && apt-get install --no-install-recommends -y libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system unicare \
    && useradd --system --gid unicare --create-home --home-dir /home/unicare unicare

COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=unicare:unicare . /app

RUN chmod +x /app/scripts/entrypoint.sh \
    && mkdir -p /app/staticfiles \
    && chown -R unicare:unicare /app/staticfiles

USER unicare

EXPOSE 8000

# Liveness, no readiness: una caida de PostgreSQL no se arregla reiniciando
# el contenedor, y sacarlo del balanceador es tarea de la readiness. Solo
# un 200 cuenta como sano (ver scripts/healthcheck.py).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "/app/scripts/healthcheck.py"]

ENTRYPOINT ["/app/scripts/entrypoint.sh"]
CMD ["web"]
