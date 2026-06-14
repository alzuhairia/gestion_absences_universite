#!/bin/bash
# ============================================
# Sauvegarde de la base de données PostgreSQL
# Utilisation : bash scripts/backup-db.sh
# À planifier quotidiennement via Task Scheduler ou cron.
# ============================================
set -euo pipefail

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Charge la config BDD depuis .env
if [ -f .env ]; then
    DB_NAME=$(grep -E '^DB_NAME=' .env | cut -d= -f2 | tr -d '[:space:]')
    DB_USER=$(grep -E '^DB_USER=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DB_NAME="${DB_NAME:-unabsences_db}"
DB_USER="${DB_USER:-unabsences}"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] Dump de ${DB_NAME} en cours..."
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

if [ -s "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[backup] Terminé : ${BACKUP_FILE} (${SIZE})"
else
    echo "[backup] ERREUR : le fichier de sauvegarde est vide !" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Rotation : conserve les 30 dernières sauvegardes
KEEP=30
COUNT=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
    REMOVE=$((COUNT - KEEP))
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -printf '%T+ %p\n' \
        | sort | head -n "$REMOVE" | cut -d' ' -f2- \
        | xargs rm -f
    echo "[backup] Rotation : ${REMOVE} ancienne(s) sauvegarde(s) supprimée(s), ${KEEP} conservée(s)."
fi
