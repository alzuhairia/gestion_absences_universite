#!/bin/bash
# ============================================
# Obtenir un certificat SSL Let's Encrypt (première fois)
# Utilisation : bash scripts/init-ssl.sh [email]
# ============================================
set -euo pipefail

# Charge DOMAIN depuis .env
if [ -f .env ]; then
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DOMAIN="${DOMAIN:-absences.infotechno.eu}"
EMAIL="${1:-admin@${DOMAIN}}"

echo "=== Configuration SSL Let's Encrypt ==="
echo "  Domaine : ${DOMAIN}"
echo "  Email   : ${EMAIL}"
echo ""

# S'assure que la stack est lancée
if ! docker compose ps --status running 2>/dev/null | grep -q nginx; then
    echo "[1/4] Démarrage de la stack..."
    docker compose up -d
    echo "Attente de l'initialisation des services..."
    sleep 15
else
    echo "[1/4] Stack déjà en cours d'exécution."
fi

# Demande de certificat via webroot
# MSYS_NO_PATHCONV empêche Git Bash (Windows) de mutiler les chemins Unix
echo "[2/4] Demande du certificat auprès de Let's Encrypt..."
MSYS_NO_PATHCONV=1 docker compose --profile certbot run --rm certbot certonly \
    --webroot \
    -w /var/www/certbot \
    -d "${DOMAIN}" \
    --email "${EMAIL}" \
    --agree-tos \
    --no-eff-email

# Copie les vrais certificats vers le dossier nginx (remplace l'auto-signé)
echo "[3/4] Installation du certificat dans nginx..."
MSYS_NO_PATHCONV=1 docker compose exec -T nginx sh -c "
    cp -L /etc/letsencrypt/live/${DOMAIN}/fullchain.pem /etc/nginx/certs/fullchain.pem
    cp -L /etc/letsencrypt/live/${DOMAIN}/privkey.pem /etc/nginx/certs/privkey.pem
"

# Recharge nginx pour utiliser le nouveau certificat
echo "[4/4] Rechargement de nginx..."
docker compose exec nginx nginx -s reload

echo ""
echo "=== Certificat SSL installé ==="
echo "  https://${DOMAIN} est maintenant sécurisé avec Let's Encrypt"
echo ""
echo "Pour renouveler (avant l'expiration dans 90 jours) :"
echo "  bash scripts/renew-ssl.sh"
echo ""
