#!/bin/bash
# ============================================
# Renew Let's Encrypt SSL certificate
# Usage: bash scripts/renew-ssl.sh
# Schedule this weekly via Task Scheduler or cron.
# Certbot only renews if the cert is near expiry (< 30 days).
# ============================================
set -euo pipefail

# MSYS_NO_PATHCONV prevents Git Bash (Windows) from mangling Unix paths
export MSYS_NO_PATHCONV=1

PRIMARY_DOMAIN="absences.infotechno.eu"
PORTABASE_DOMAIN="portabase.infotechno.eu"
FIT_DOCKHAND_CERT="fit.infotechno.eu"
TINYAUTH_DOMAIN="tinyauth.infotechno.eu"

echo "[renew] Checking certificates for ${PRIMARY_DOMAIN}, ${PORTABASE_DOMAIN}, ${TINYAUTH_DOMAIN}, fit.infotechno.eu and dockhand.infotechno.eu..."

# Attempt renewal (certbot skips if not near expiry)
docker compose --profile certbot run --rm certbot renew

# Certificates are referenced directly from /etc/letsencrypt/live by nginx.
# Reloading is enough after certbot renew updates the symlinks.
docker compose exec nginx nginx -s reload

echo "[renew] Done."
