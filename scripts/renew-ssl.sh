#!/bin/bash
# ============================================
# Renew Let's Encrypt SSL certificate
# Usage: bash scripts/renew-ssl.sh
# Schedule this weekly via Task Scheduler or cron.
# Certbot only renews if the cert is near expiry (< 30 days).
# ============================================
set -euo pipefail

if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DOMAIN="${DOMAIN:-absences.infotechno.eu}"

echo "[renew] Checking certificate renewal for ${DOMAIN}..."

# Attempt renewal (certbot skips if not near expiry)
docker compose --profile certbot run --rm certbot renew

# Copy certs and reload nginx (safe even if no renewal happened)
docker compose exec -T nginx sh -c "
    cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/nginx/certs/fullchain.pem
    cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/nginx/certs/privkey.pem
"
docker compose exec nginx nginx -s reload

echo "[renew] Done."
