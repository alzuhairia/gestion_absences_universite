#!/bin/sh
set -eu

MONITORING_USER="${MONITORING_USER:-}"
MONITORING_PASSWORD="${MONITORING_PASSWORD:-}"
HTPASSWD_FILE="/etc/nginx/conf.d/.htpasswd"

if [ -z "$MONITORING_USER" ] || [ -z "$MONITORING_PASSWORD" ]; then
    echo "[nginx] MONITORING_USER or MONITORING_PASSWORD not set, skipping htpasswd."
    touch "$HTPASSWD_FILE"
    exit 0
fi

HASH=$(openssl passwd -apr1 "$MONITORING_PASSWORD")
printf "%s:%s\n" "$MONITORING_USER" "$HASH" > "$HTPASSWD_FILE"
echo "[nginx] Basic auth configured for monitoring (user: ${MONITORING_USER})."
