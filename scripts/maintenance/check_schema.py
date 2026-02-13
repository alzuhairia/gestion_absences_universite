import argparse
import re
import sqlite3
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "db.sqlite3"


def _validate_identifier(name: str, label: str) -> None:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        raise ValueError(f"Invalid {label}: {name}")


def check_schema(table_name: str, column_name: str) -> int:
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")

    if not DB_PATH.exists():
        print(f"{DB_PATH} not found.")
        print("Use scripts/maintenance/check_schema_django.py for PostgreSQL/Docker.")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        cursor.execute(f"PRAGMA table_info({table_name})")
        rows = cursor.fetchall()

        if not rows:
            print(f"Table '{table_name}' not found in SQLite database: {DB_PATH}")
            return 1

        columns = [row[1] for row in rows]
        print(f"Columns found in '{table_name}': {columns}")

        if column_name in columns:
            print(f"SUCCESS: '{column_name}' column found.")
            return 0

        print(f"FAILURE: '{column_name}' column not found.")
        return 2
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a SQLite table schema")
    parser.add_argument("--table", default="justification")
    parser.add_argument("--column", default="commentaire_gestion")
    args = parser.parse_args()

    return check_schema(args.table, args.column)


if __name__ == "__main__":
    raise SystemExit(main())

