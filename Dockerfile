# ============================================
# Dockerfile pour UniAbsences - Application Django
# ============================================
# IMPORTANT POUR LA SOUTENANCE :
# Ce Dockerfile crée une image Docker optimisée pour la production
# Il utilise un build multi-stage pour réduire la taille de l'image finale

# ============================================
# ÉTAPE 1 : Image de base Python
# ============================================
FROM python:3.13-slim AS base

# Définir les variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Installer les dépendances système nécessaires
# Note: postgresql-client et libpq-dev sont essentiels pour psycopg2
# AJOUT : 'curl' est nécessaire pour le HEALTHCHECK (Autoheal)
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    gosu \
    gcc \
    python3-dev \
    libpq-dev \
    libmagic1 \
    file \
    libjpeg-dev \
    zlib1g-dev \
    libtiff-dev \
    libfreetype6-dev \
    libwebp-dev \
    && rm -rf /var/lib/apt/lists/*

# ============================================
# ÉTAPE 2 : Installation des dépendances Python
# ============================================
FROM base AS dependencies

# Définir le répertoire de travail
WORKDIR /app

# Copier uniquement le fichier requirements.txt d'abord
COPY requirements.txt /app/

# Installation des dépendances
# IMPORTANT : Assurez-vous que requirements.txt contient psycopg2-binary==2.9.10
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefer-binary -r requirements.txt

# ============================================
# ÉTAPE 3 : Image finale de production
# ============================================
FROM dependencies AS production

WORKDIR /app

# Créer l'utilisateur non-root (optionnel maintenant, mais on le garde pour la propreté)
RUN useradd -m -u 1000 django

# Créer les répertoires nécessaires
RUN mkdir -p /app/staticfiles /app/media /app/logs && \
    chown -R django:django /app

# Copier tout le code de l'application
COPY --chown=django:django . /app/

# Script d'entrée
COPY --chown=django:django entrypoint.sh /app/
# C'est cette ligne qui sauve la vie : elle convertit le fichier au format Linux
RUN sed -i 's/\r$//g' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Exécuter le conteneur applicatif en utilisateur non-root.
USER django

# Exposer le port par défaut de Gunicorn
EXPOSE 8000

# Commande de démarrage
ENTRYPOINT ["/app/entrypoint.sh"]

# Commande par défaut : lancer Gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "--access-logfile", "-", "--access-logformat", "%(h)s %(l)s %(u)s %(t)s \"%(m)s %(U)s\" %(s)s %(b)s \"%(f)s\" \"%(a)s\"", "--error-logfile", "-", "config.wsgi:application"]
