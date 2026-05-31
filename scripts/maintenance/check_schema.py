"""
UniAbsences – scripts.maintenance.check_schema
===============================================

Lightweight schema inspector for the project's SQLite database.

This script reads the SQLite file directly (without loading Django) and
checks whether a specific column exists in a specific table.  It is useful
for quick local verification before or after applying migrations in
environments where the full Django stack is not available.

For PostgreSQL / Docker deployments use ``check_schema_django.py`` instead,
which goes through Django's database connection layer.

Usage
-----
Run from the project root::

    python scripts/maintenance/check_schema.py --table justification --column commentaire_gestion

Exit codes
----------
0  Column found.
1  Database file not found, or table not found.
2  Table found but column missing.

Part of: UniAbsences maintenance / schema inspection layer.
"""

import argparse
import re
import sqlite3
from pathlib import Path

# Resolve the SQLite database path relative to this file's location.
# This file lives at <project_root>/scripts/maintenance/check_schema.py, so:
#   .parent           → .../scripts/maintenance/
#   .parent.parent    → .../scripts/
#   .parent.parent.parent → <project_root>/
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_PATH = BASE_DIR / "db.sqlite3"


def _validate_identifier(name: str, label: str) -> None:
    """Validate that ``name`` is a safe SQL identifier.

    Only alphanumeric characters and underscores are accepted, and the name
    must start with a letter or underscore.  This guards against SQL injection
    in the ``PRAGMA table_info(...)`` call below.

    Parameters
    ----------
    name:
        The identifier string to validate (table name or column name).
    label:
        A human-readable description used in the error message
        (e.g. ``"table name"`` or ``"column name"``).

    Raises
    ------
    ValueError
        If ``name`` does not match the safe identifier pattern.
    """
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
        raise ValueError(f"Invalid {label}: {name}")


def check_schema(table_name: str, column_name: str) -> int:
    """Check whether ``column_name`` exists in ``table_name`` in the SQLite DB.

    Opens the SQLite file at ``DB_PATH``, runs ``PRAGMA table_info`` for the
    given table, and inspects the result set for the requested column.

    Parameters
    ----------
    table_name:
        Name of the database table to inspect (must be a valid SQL identifier).
    column_name:
        Name of the column to look for within that table.

    Returns
    -------
    int
        0 if the column is found, 1 if the DB/table is missing, 2 if the
        table exists but the column is absent.

    Raises
    ------
    ValueError
        If either identifier fails the safety check in ``_validate_identifier``.
    """
    # Reject any identifier that could be used for SQL injection.
    _validate_identifier(table_name, "table name")
    _validate_identifier(column_name, "column name")

    # Abort early when there is no local SQLite file – the caller likely needs
    # check_schema_django.py for a remote/containerised database.
    if not DB_PATH.exists():
        print(f"{DB_PATH} not found.")
        print("Use scripts/maintenance/check_schema_django.py for PostgreSQL/Docker.")
        return 1

    conn = sqlite3.connect(DB_PATH)
    try:
        cursor = conn.cursor()
        # SQLite's PRAGMA table_info returns one row per column:
        #   (cid, name, type, notnull, dflt_value, pk)
        cursor.execute(f"PRAGMA table_info({table_name})")
        rows = cursor.fetchall()

        if not rows:
            # An empty result set means the table does not exist.
            print(f"Table '{table_name}' not found in SQLite database: {DB_PATH}")
            return 1

        # Extract just the column names (index 1 in each PRAGMA row).
        columns = [row[1] for row in rows]
        print(f"Columns found in '{table_name}': {columns}")

        if column_name in columns:
            print(f"SUCCESS: '{column_name}' column found.")
            return 0

        print(f"FAILURE: '{column_name}' column not found.")
        return 2
    finally:
        # Always close the connection, even if an exception is raised.
        conn.close()


def main() -> int:
    """Parse command-line arguments and run the schema check.

    Returns
    -------
    int
        The exit code returned by ``check_schema``.
    """
    parser = argparse.ArgumentParser(description="Check a SQLite table schema")
    parser.add_argument("--table", default="justification",
                        help="Table to inspect (default: justification)")
    parser.add_argument("--column", default="commentaire_gestion",
                        help="Column to look for (default: commentaire_gestion)")
    args = parser.parse_args()

    return check_schema(args.table, args.column)


if __name__ == "__main__":
    raise SystemExit(main())
