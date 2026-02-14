import argparse
import os
import re
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.db import connection
from django.db.utils import OperationalError


django.setup()


def _validate_identifier(name: str, label: str) -> None:
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        raise ValueError(f"Invalid {label}: {name}")


def _fetch_columns(table_name: str) -> list[str]:
    vendor = connection.vendor

    with connection.cursor() as cursor:
        if vendor == "postgresql":
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
                ORDER BY ordinal_position
                """,
                [table_name],
            )
            return [row[0] for row in cursor.fetchall()]

        if vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({table_name})")
            return [row[1] for row in cursor.fetchall()]

        cursor.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = %s
            ORDER BY ordinal_position
            """,
            [table_name],
        )
        return [row[0] for row in cursor.fetchall()]


def check_schema_django(table_name: str, column_name: str) -> int:
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")

    print(
        f"Checking columns for table '{table_name}' using Django connection "
        f"({connection.vendor})..."
    )

    try:
        columns = _fetch_columns(table_name)
    except OperationalError as exc:
        print(f"Database connection error: {exc}")
        print("Tip: run this script from the `web` container or with a reachable DB host.")
        return 1
    if not columns:
        print(f"Table '{table_name}' not found or has no columns.")
        return 1

    print(f"Columns found: {columns}")

    if column_name in columns:
        print(f"SUCCESS: '{column_name}' column found.")
        return 0

    print(f"FAILURE: '{column_name}' column not found.")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Check schema via Django DB connection")
    parser.add_argument("--table", default="justification")
    parser.add_argument("--column", default="commentaire_gestion")
    args = parser.parse_args()

    return check_schema_django(args.table, args.column)


if __name__ == "__main__":
    raise SystemExit(main())

