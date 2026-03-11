#!/bin/bash
# ============================================
# Backup PostgreSQL database
# Usage: bash scripts/backup-db.sh
# Schedule daily via Task Scheduler or cron.
# ============================================
set -euo pipefail

BACKUP_DIR="./backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Load DB config from .env
if [ -f .env ]; then
    DB_NAME=$(grep -E '^DB_NAME=' .env | cut -d= -f2 | tr -d '[:space:]')
    DB_USER=$(grep -E '^DB_USER=' .env | cut -d= -f2 | tr -d '[:space:]')
fi
DB_NAME="${DB_NAME:-unabsences_db}"
DB_USER="${DB_USER:-unabsences}"

BACKUP_FILE="${BACKUP_DIR}/${DB_NAME}_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"

echo "[backup] Dumping ${DB_NAME}..."
docker compose exec -T db pg_dump -U "$DB_USER" "$DB_NAME" | gzip > "$BACKUP_FILE"

if [ -s "$BACKUP_FILE" ]; then
    SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
    echo "[backup] Done: ${BACKUP_FILE} (${SIZE})"
else
    echo "[backup] ERROR: backup file is empty!" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

# Rotate: keep last 30 backups
KEEP=30
COUNT=$(find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f | wc -l)
if [ "$COUNT" -gt "$KEEP" ]; then
    REMOVE=$((COUNT - KEEP))
    find "$BACKUP_DIR" -name "${DB_NAME}_*.sql.gz" -type f -printf '%T+ %p\n' \
        | sort | head -n "$REMOVE" | cut -d' ' -f2- \
        | xargs rm -f
    echo "[backup] Rotated: removed ${REMOVE} old backup(s), keeping ${KEEP}."
fi
