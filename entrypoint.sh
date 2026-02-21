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

  if command -v runuser >/dev/null 2>&1; then
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

echo "[entrypoint] Waiting for PostgreSQL and ensuring target database exists..."
python - <<'PY'
import os
import sys
import time

import psycopg2
from psycopg2 import OperationalError, sql


db_host = os.getenv("DB_HOST", "db")
db_port = int(os.getenv("DB_PORT", "5432"))
db_user = os.getenv("DB_USER", "postgres")
db_password = os.getenv("DB_PASSWORD", "")
db_name = os.getenv("DB_NAME", "gestion_absences_universite")
max_attempts = int(os.getenv("DB_WAIT_MAX_ATTEMPTS", "60"))
sleep_seconds = float(os.getenv("DB_WAIT_SLEEP_SECONDS", "2"))

for attempt in range(1, max_attempts + 1):
    try:
        conn = psycopg2.connect(
            dbname="postgres",
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            connect_timeout=5,
        )
        conn.autocommit = True

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (db_name,))
            if cur.fetchone() is None:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(db_name)))
                print(f"[entrypoint] Database '{db_name}' created.")
            else:
                print(f"[entrypoint] Database '{db_name}' already exists.")

        conn.close()
        print("[entrypoint] PostgreSQL is ready.")
        break
    except OperationalError as exc:
        if attempt == max_attempts:
            print(f"[entrypoint] PostgreSQL unavailable after {max_attempts} attempts: {exc}")
            sys.exit(1)
        print(
            f"[entrypoint] PostgreSQL not ready (attempt {attempt}/{max_attempts}), "
            f"retrying in {sleep_seconds:.0f}s..."
        )
        time.sleep(sleep_seconds)
PY

echo "[entrypoint] Running migrations..."
run_as_app python manage.py migrate --noinput

echo "[entrypoint] Collecting static files..."
run_as_app python manage.py collectstatic --noinput --clear

echo "[entrypoint] Launching application process..."
if [ "$(id -u)" -eq 0 ]; then
  if command -v runuser >/dev/null 2>&1; then
    exec runuser -u django -- "$@"
  else
    exec su -s /bin/bash django -c "$*"
  fi
else
  exec "$@"
fi
