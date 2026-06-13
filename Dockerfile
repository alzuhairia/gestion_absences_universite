# ============================================
# Dockerfile pour UniAbsences - Application Django
# ============================================

# ============================================
# ÉTAPE 1 : Image Python de base
# ============================================
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Dépendances système nécessaires à l'exécution.
# Liste maintenue minimale pour réduire la surface des CVE au niveau de l'OS lors des scans d'image.
# psycopg2-binary intègre les bibliothèques client PostgreSQL, donc pas besoin de postgresql-client/libpq-dev.
RUN apt-get update \
    && apt-get -y upgrade \
    && apt-get install -y --no-install-recommends \
        curl \
        libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# ÉTAPE 2 : Dépendances Python
# ============================================
FROM base AS dependencies

WORKDIR /app

COPY requirements.txt /app/

RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# ============================================
# ÉTAPE 3 : Image de production
# ============================================
FROM dependencies AS production

WORKDIR /app

RUN useradd -m -u 1000 django

RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R django:django /app

COPY --chown=django:django . /app/
RUN sed -i 's/\r$//g' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# USER django n'est volontairement PAS défini ici.
# L'entrypoint s'exécute en tant que root pour ajuster les permissions des volumes montés,
# puis bascule vers l'utilisateur django via runuser/exec.

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]

CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(h)s %(l)s %(u)s %(t)s \"%(m)s %(U)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\"", "--error-logfile", "-", "config.wsgi:application"]
