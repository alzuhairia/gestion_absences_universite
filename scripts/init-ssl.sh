#!/bin/bash
# ============================================
# Obtain Let's Encrypt SSL certificate (first time)
# Usage: bash scripts/init-ssl.sh [email]
# ============================================
set -euo pipefail

# Load DOMAIN from .env
if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DOMAIN="${DOMAIN:-absences.infotechno.eu}"
EMAIL="${1:-admin@${DOMAIN}}"

echo "=== Let's Encrypt SSL Setup ==="
echo "  Domain: ${DOMAIN}"
echo "  Email:  ${EMAIL}"
echo ""

# Ensure the stack is running
if ! docker compose ps --status running 2>/dev/null | grep -q nginx; then
    echo "[1/4] Starting stack..."
    docker compose up -d
    echo "Waiting for services to initialize..."
    sleep 15
else
    echo "[1/4] Stack already running."
fi

# Request certificate via webroot
echo "[2/4] Requesting certificate from Let's Encrypt..."
docker compose --profile certbot run --rm certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d "${DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email

# Copy real certs to nginx cert dir (replaces self-signed)
echo "[3/4] Installing certificate in nginx..."
docker compose exec -T nginx sh -c "
    cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/nginx/certs/fullchain.pem
    cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/nginx/certs/privkey.pem
"

# Reload nginx to use new certificate
echo "[4/4] Reloading nginx..."
docker compose exec nginx nginx -s reload

echo ""
echo "=== SSL certificate installed ==="
echo "  https://${DOMAIN} is now secured with Let's Encrypt"
echo ""
echo "To renew (before expiry in 90 days):"
echo "  bash scripts/renew-ssl.sh"
echo ""
