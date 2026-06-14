#!/bin/bash
# ============================================
# Renouvelle le certificat SSL Let's Encrypt
# Utilisation : bash scripts/renew-ssl.sh
# À planifier chaque semaine via Task Scheduler ou cron.
# Certbot ne renouvelle que si le certificat est proche de l'expiration (< 30 jours).
# ============================================
set -euo pipefail

# MSYS_NO_PATHCONV empêche Git Bash (Windows) de mutiler les chemins Unix
export MSYS_NO_PATHCONV=1

if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DOMAIN="${DOMAIN:-absences.infotechno.eu}"

echo "[renew] Vérification du renouvellement du certificat pour ${DOMAIN}..."

# Tentative de renouvellement (certbot ignore si pas proche de l'expiration)
docker compose --profile certbot run --rm certbot renew

# Copie les certificats et recharge nginx (sans risque même sans renouvellement)
docker compose exec -T nginx sh -c "
    cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/nginx/certs/fullchain.pem
    cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/nginx/certs/privkey.pem
"
docker compose exec nginx nginx -s reload

echo "[renew] Terminé."
