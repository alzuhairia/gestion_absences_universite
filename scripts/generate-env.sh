#!/bin/bash
# ============================================
# Generate production .env file with secure random secrets
# Usage: bash scripts/generate-env.sh [domain]
# ============================================
set -euo pipefail

DOMAIN="${1:-absences.infotechno.eu}"
ENV_FILE=".env"

if [ -f "$ENV_FILE" ]; then
    echo "ERROR: .env already exists."
    echo "Rename or delete it before running this script."
    exit 1
fi

# Generate cryptographically secure random values
SECRET_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(50))")
DB_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
REDIS_PASSWORD=$(python -c "import secrets; print(secrets.token_urlsafe(24))")
HEALTHCHECK_TOKEN=$(python -c "import secrets; print(secrets.token_urlsafe(32))")

cat > "$ENV_FILE" << EOF
# ============================================
# Production environment — generated $(date +%Y-%m-%d)
# Domain: ${DOMAIN}
# ============================================

# Django core
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

# Database
DB_NAME=unabsences_db
DB_USER=unabsences
DB_PASSWORD=${DB_PASSWORD}
DB_HOST=db
DB_PORT=5432
POSTGRES_PASSWORD=${DB_PASSWORD}

# Redis
REDIS_PASSWORD=${REDIS_PASSWORD}
REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/1
REDIS_MAX_CONNECTIONS=100
REDIS_CACHE_TIMEOUT=300

# Rate limits
HEALTHCHECK_RATE_LIMIT=12/m
LOGIN_RATE_LIMIT_IP=20/5m
LOGIN_RATE_LIMIT_COMBINED=5/5m

# Healthcheck
HEALTHCHECK_TOKEN=${HEALTHCHECK_TOKEN}
HEALTHCHECK_TOKEN_PREVIOUS=
HEALTHCHECK_ALLOWLIST_CIDRS=127.0.0.1/32,::1/128,172.30.0.14/32

# Domain (used by nginx + SSL scripts)
DOMAIN=${DOMAIN}
EOF

echo ""
echo "=== .env generated successfully ==="
echo "  Domain:   ${DOMAIN}"
echo "  DB User:  unabsences"
echo "  Secrets:  randomly generated"
echo ""
echo "Next steps:"
echo "  1. docker compose up -d --build"
echo "  2. bash scripts/init-ssl.sh your@email.com"
echo "  3. Visit https://${DOMAIN}/setup/ to create admin account"
echo ""
