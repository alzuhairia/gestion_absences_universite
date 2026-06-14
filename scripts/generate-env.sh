#!/bin/bash
# ============================================
# Génère un fichier .env de production avec des secrets aléatoires sécurisés
# Utilisation : bash scripts/generate-env.sh [domaine]
# ============================================
set -euo pipefail

DOMAIN="${1:-absences.infotechno.eu}"
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    echo "ERREUR : .env existe déjà."
    echo "Renommez-le ou supprimez-le avant d'exécuter ce script."
    exit 1
fi

# Génère des valeurs aléatoires cryptographiquement sûres
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
DB_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
REDIS_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
HEALTHCHECK_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

cat > "$ENV_FILE" << EOF
# ============================================
# Environnement de production — généré le $(date +%Y-%m-%d)
# Domaine : ${DOMAIN}
# ============================================

# Cœur Django
SECRET_KEY=${SECRET_KEY}
DEBUG=False
ALLOWED_HOSTS=${DOMAIN}
CSRF_TRUSTED_ORIGINS=https://${DOMAIN}

# Reverse proxy / HTTPS
USE_X_FORWARDED_PROTO=True
USE_X_FORWARDED_HOST=False
TRUSTED_PROXY_CIDRS=172.30.0.10/32
SECURE_SSL_REDIRECT=True
SECURE_HSTS_SECONDS=31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS=True
SECURE_HSTS_PRELOAD=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True

# Base de données
DB_NAME=unabsences_db
DB_USER=unabsences
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=db
DB_PORT=5432

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/1
REDIS_MAX_CONNECTIONS=100
REDIS_CACHE_TIMEOUT=300

# Limites de débit
HEALTHCHECK_RATE_LIMIT=12/m
LOGIN_RATE_LIMIT_IP=20/5m
LOGIN_RATE_LIMIT_COMBINED=5/5m

# Healthcheck
HEALTHCHECK_TOKEN=${HEALTHCHECK_TOKEN}
HEALTHCHECK_TOKEN_PREVIOUS=
HEALTHCHECK_ALLOWLIST_CIDRS=127.0.0.1/32,::1/128,172.30.0.14/32

# Domaine (utilisé par nginx + scripts SSL)
DOMAIN=${DOMAIN}
EOF

echo ""
echo "=== .env généré avec succès ==="
echo "  Domaine          : ${DOMAIN}"
echo "  Utilisateur BDD  : unabsences"
echo "  Secrets          : générés aléatoirement"
echo ""
echo "Étapes suivantes :"
echo "  1. docker compose up -d --build"
echo "  2. bash scripts/init-ssl.sh votre@email.com"
echo "  3. Aller sur https://${DOMAIN}/setup/ pour créer le compte admin"
echo ""
