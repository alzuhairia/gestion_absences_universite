# ============================================
# Dockerfile for UniAbsences - Django app
# ============================================

# ============================================
# STAGE 1: Base Python image
# ============================================
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# System deps needed at runtime.
# Keep this list minimal to reduce OS-level CVE surface in image scans.
# psycopg2-binary bundles PostgreSQL client libs, so no postgresql-client/libpq-dev.
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get install -y --no-install-recommends \
        curl \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# STAGE 2: Python dependencies
# ============================================
FROM base AS dependencies

WORKDIR /app

COPY requirements.txt /app/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# ============================================
# STAGE 3: Production image
# ============================================
FROM dependencies AS production

WORKDIR /app

RUN useradd -m -u 1000 django

RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R django:django /app

COPY --chown=django:django . /app/
COPY --chown=django:django entrypoint.sh /app/
RUN sed -i 's/\r$//g' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

USER django

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(h)s %(l)s %(u)s %(t)s \"%(m)s %(U)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\"", "--error-logfile", "-", "config.wsgi:application"]
