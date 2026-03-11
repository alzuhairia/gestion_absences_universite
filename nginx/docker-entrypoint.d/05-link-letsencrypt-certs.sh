#!/bin/sh
set -eu

CERT_DIR="/etc/nginx/certs"
DOMAIN="${DOMAIN:-}"
LE_LIVE="/etc/letsencrypt/live/${DOMAIN}"

if [ -z "$DOMAIN" ] || [ "$DOMAIN" = "localhost" ]; then
    echo "[nginx] No DOMAIN set, skipping Let's Encrypt cert linking."
    exit 0
fi

if [ -f "${LE_LIVE}/fullchain.pem" ] && [ -f "${LE_LIVE}/privkey.pem" ]; then
    echo "[nginx] Found Let's Encrypt certificate for ${DOMAIN}, copying..."
    mkdir -p "$CERT_DIR"
    cp -L "${LE_LIVE}/fullchain.pem" "${CERT_DIR}/fullchain.pem"
    cp -L "${LE_LIVE}/privkey.pem" "${CERT_DIR}/privkey.pem"
    echo "[nginx] Let's Encrypt certificate installed."
else
    echo "[nginx] No Let's Encrypt cert for ${DOMAIN} yet. Self-signed will be used."
fi
