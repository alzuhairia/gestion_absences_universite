"""
UniAbsences – scripts.maintenance.check_schema_django
======================================================

Schema inspector that uses Django's active database connection to verify
whether a specific column exists in a specific table.

Unlike ``check_schema.py``, which opens the SQLite file directly, this
module goes through Django's ORM connection layer and therefore works with
any configured backend (SQLite, PostgreSQL, MySQL, etc.).  It is the
preferred tool for Docker / CI environments where the database is hosted
remotely.

Usage
-----
Run from inside the ``web`` container or from a machine that can reach the
configured database::

    python scripts/maintenance/check_schema_django.py --table justification --column commentaire_gestion

Exit codes
----------
0  Column found.
1  Connection error, or table not found / has no columns.
2  Table found but column missing.

Part of: UniAbsences maintenance / schema inspection layer.
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Bootstrap Django before any app imports.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django
from django.db import connection
from django.db.utils import OperationalError

django.setup()


def _validate_identifier(name: str, label: str) -> None:
    """Validate that ``name`` is a safe SQL identifier.

    Parameters
    ----------
    name:
        The identifier string to validate.
    label:
        Human-readable description used in the error message
        (e.g. ``"table name"`` or ``"column name"``).

    Raises
    ------
    ValueError
        If ``name`` does not match the pattern ``^[A-Za-z_][A-Za-z0-9_]*$``.
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        raise ValueError(f"Invalid {label}: {name}")


def _fetch_columns(table_name: str) -> list[str]:
    """Return the ordered list of column names for ``table_name``.

    The query used depends on the active database vendor so that the function
    works correctly for PostgreSQL, SQLite, and generic ANSI-SQL backends.

    Parameters
    ----------
    table_name:
        Name of the table whose columns should be retrieved.

    Returns
    -------
    list[str]
        Column names in their declared order, or an empty list when the table
        does not exist.

    Raises
    ------
    django.db.utils.OperationalError
        If the database connection cannot be established.
    """
    vendor = connection.vendor

    with connection.cursor() as cursor:
        if vendor == "postgresql":
            # Use information_schema scoped to the current schema so that
            # tables in other schemas are not accidentally matched.
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
            # SQLite exposes column metadata through a PRAGMA statement.
            # Each row is (cid, name, type, notnull, dflt_value, pk).
            cursor.execute(f"PRAGMA table_info({table_name})")
            return [row[1] for row in cursor.fetchall()]

        # Fallback for MySQL and other ANSI-SQL backends.
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
    """Check whether ``column_name`` exists in ``table_name`` via Django.

    Parameters
    ----------
    table_name:
        Name of the database table to inspect.
    column_name:
        Name of the column to look for.

    Returns
    -------
    int
        0 if the column is found, 1 on connection/table error, 2 if the
        column is absent.

    Raises
    ------
    ValueError
        If either identifier fails the safety validation.
    """
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
    """Parse command-line arguments and run the Django-backed schema check.

    Returns
    -------
    int
        The exit code returned by ``check_schema_django``.
    """
    parser = argparse.ArgumentParser(description="Check schema via Django DB connection")
    parser.add_argument("--table", default="justification",
                        help="Table to inspect (default: justification)")
    parser.add_argument("--column", default="commentaire_gestion",
                        help="Column to look for (default: commentaire_gestion)")
    args = parser.parse_args()

    return check_schema_django(args.table, args.column)


if __name__ == "__main__":
    raise SystemExit(main())
