#!/bin/sh
set -eu

CERT_DIR="/etc/nginx/certs"
DOMAIN="${DOMAIN:-}"
LE_LIVE="/etc/letsencrypt/live/${DOMAIN}"

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "localhost" ]; then
    echo "[nginx] Aucun DOMAIN défini, liaison du certificat Let's Encrypt ignorée."
    exit 0
fi

if [ -f "${LE_LIVE}/fullchain.pem" ] && [ -f "${LE_LIVE}/privkey.pem" ]; then
    echo "[nginx] Certificat Let's Encrypt trouvé pour ${DOMAIN}, copie en cours..."
    mkdir -p "$CERT_DIR"
    cp -L "${LE_LIVE}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
    cp -L "${LE_LIVE}/privkey.pem" "${CERT_DIR}/privkey.pem"
    echo "[nginx] Certificat Let's Encrypt installé."
else
    echo "[nginx] Pas encore de certificat Let's Encrypt pour ${DOMAIN}. Le certificat auto-signé sera utilisé."
fi
