#!/bin/bash
# ============================================
# Container entrypoint for UniAbsences
# ============================================
set -euo pipefail

echo "[entrypoint] Starting UniAbsences container..."

if [ "$(id -u)" -eq 0 ]; then
  mkdir -p /app/staticfiles /app/media /app/logs /tmp
  chown -R django:django /app/staticfiles /app/media /app/logs
  chmod -R u+rwX,g+rwX /app/staticfiles /app/media /app/logs

  if command -v gosu >/dev/null 2>&1; then
    run_as_app() {
      gosu django "$@"
    }
  elif command -v runuser >/dev/null 2>&1; then
    run_as_app() {
      runuser -u django -- "$@"
    }
  else
    run_as_app() {
      su -s /bin/bash django -c "$*"
    }
  fi
else
  run_as_app() {
    "$@"
  }
fi

echo "[entrypoint] Waiting for PostgreSQL..."
until PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -U "${DB_USER}" -d "postgres" -c '\q' 2>/dev/null; do
  echo "[entrypoint] PostgreSQL not ready yet, retrying in 2 seconds..."
  sleep 2
done
echo "[entrypoint] PostgreSQL is ready."

echo "[entrypoint] Ensuring database '${DB_NAME}' exists..."
PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -U "${DB_USER}" -d "postgres" -tc \
  "SELECT 1 FROM pg_database WHERE datname = '${DB_NAME}'" | \
  grep -q 1 || \
  PGPASSWORD="${DB_PASSWORD}" psql -h "${DB_HOST}" -U "${DB_USER}" -d "postgres" -c \
  "CREATE DATABASE ${DB_NAME}"

echo "[entrypoint] Running migrations..."
run_as_app python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
run_as_app python manage.py collectstatic --noinput --clear

echo "[entrypoint] Launching application process..."
if [ "$(id -u)" -eq 0 ]; then
  if command -v gosu >/dev/null 2>&1; then
    exec gosu django "$@"
  elif command -v runuser >/dev/null 2>&1; then
    exec runuser -u django -- "$@"
  else
    exec su -s /bin/bash django -c "$*"
  fi
else
  exec "$@"
fi
