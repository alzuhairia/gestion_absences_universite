"""
UniAbsences – scripts.maintenance.force_add_column
===================================================

Emergency DDL fallback that adds the ``state`` column to the
``justification`` table via a raw ``ALTER TABLE`` statement.

Background
----------
When the Django migration that introduces ``justification.state`` cannot be
applied normally (e.g. because of a conflicting migration history or a
partially applied state), this script provides a direct SQL escape hatch.
The column is added with a default value of ``'EN_ATTENTE'`` so that
existing rows receive a valid status immediately.

Warning
-------
This script bypasses Django's migration framework entirely.  After running
it, the corresponding migration must be marked as applied (``--fake``) to
keep the migration history consistent::

    python manage.py migrate absences <migration_name> --fake

Usage
-----
Run from the project root as a last resort when the migration fails::

    python scripts/maintenance/force_add_column.py

Part of: UniAbsences maintenance / emergency schema repair layer.
"""

import os
import sys
from pathlib import Path

# Bootstrap Django so that the active database connection is available.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection


def force_add_column() -> None:
    """Add the ``state`` column to ``justification`` via raw SQL.

    Executes ``ALTER TABLE justification ADD COLUMN state varchar(20)``
    with a default of ``'EN_ATTENTE'``.  If the column already exists the
    database will raise an error, which is caught and printed rather than
    re-raised, so the script exits cleanly in both cases.
    """
    with connection.cursor() as cursor:
        print("Attempting to force add 'state' column to 'justification'...")
        try:
            # Use a DEFAULT so that existing rows are immediately valid.
            cursor.execute(
                "ALTER TABLE justification ADD COLUMN state varchar(20) DEFAULT 'EN_ATTENTE';"
            )
            print("SUCCESS: SQL executed.")
        except Exception as e:
            # Most likely cause: the column already exists.  Log and continue.
            print(f"FAILURE: {e}")


if __name__ == '__main__':
    force_add_column()
