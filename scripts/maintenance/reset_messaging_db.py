"""
UniAbsences – scripts.maintenance.reset_messaging_db
=====================================================

Resets the messaging application's database state so that Django migrations
can recreate the schema from scratch.

What this script does
---------------------
1. Drops the ``message`` table if it exists (data will be lost).
2. Deletes all rows from ``django_migrations`` where ``app = 'messaging'``
   so that ``python manage.py migrate messaging`` treats the app as brand new.

When to use
-----------
Run this script when the ``messaging`` app's migrations are in an
irrecoverable state (e.g. the table schema no longer matches the migration
history) and a clean re-migration is the fastest solution.  After running
the script, apply the migrations normally::

    python scripts/maintenance/reset_messaging_db.py
    python manage.py migrate messaging

Warning
-------
All data in the ``message`` table is **permanently deleted** by this script.
Do not run it on a production database unless data loss is acceptable or a
backup has been taken.

Part of: UniAbsences maintenance / schema repair layer.
"""

import os
import sys
from pathlib import Path

# Bootstrap Django so that the database connection is available.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection


def reset_messaging_db() -> None:
    """Drop the ``message`` table and clear the messaging migration history.

    Executes two raw SQL statements inside the same database cursor context:

    1. ``DROP TABLE IF EXISTS message`` – removes the physical table.
    2. ``DELETE FROM django_migrations WHERE app = 'messaging'`` – removes
       migration history rows so Django considers the app unmigrated.
    """
    print("Resetting Messaging App Database limits...")
    with connection.cursor() as cursor:
        # Remove the table; IF EXISTS prevents an error when it is absent.
        cursor.execute("DROP TABLE IF EXISTS message;")
        print("Dropped table 'message'.")

        # Clear recorded migrations so that ``migrate`` will replay them.
        cursor.execute("DELETE FROM django_migrations WHERE app = 'messaging';")
        print("Cleared migration history for 'messaging'.")


if __name__ == "__main__":
    reset_messaging_db()
