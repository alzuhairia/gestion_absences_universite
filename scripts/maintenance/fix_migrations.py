"""
UniAbsences – scripts.maintenance.fix_migrations
================================================

Patches the Django migration history table to insert a missing
``academic_sessions.0001_initial`` entry.

Background
----------
The ``enrollments`` app depends on ``academic_sessions`` at the database
level (foreign key on ``AnneeAcademique``).  If the migration history was
recorded out of order – for example because ``enrollments.0001_initial``
was applied before ``academic_sessions.0001_initial`` – Django will refuse
to run subsequent migrations.

This script inspects the ``django_migrations`` table and, if the
``academic_sessions.0001_initial`` row is absent, inserts it with a
timestamp one second *before* ``enrollments.0001_initial`` so that the
ordering constraint is satisfied.

Usage
-----
Run from the project root once, then execute the normal migrate command::

    python scripts/maintenance/fix_migrations.py
    python manage.py migrate

Part of: UniAbsences maintenance / migration repair layer.
"""

import os
import sys
from pathlib import Path

# Bootstrap Django so that the ORM connection is available.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.db import connection
from datetime import timedelta


def fix_migration_history() -> None:
    """Insert the missing ``academic_sessions.0001_initial`` migration record.

    Checks whether the row already exists; if it does, the function returns
    without making any changes.  Otherwise it reads the applied timestamp of
    ``enrollments.0001_initial`` and inserts the missing row one second
    earlier.

    Raises
    ------
    Exception
        Propagates any database error encountered during the insert so that
        the caller can log and re-raise it.
    """
    with connection.cursor() as cursor:
        # Check if the target migration is already recorded.
        cursor.execute("""
            SELECT id FROM django_migrations
            WHERE app = 'academic_sessions' AND name = '0001_initial'
        """)
        exists = cursor.fetchone()

        if exists:
            print("[OK] Migration academic_sessions.0001_initial existe deja")
            return

        # Read the applied timestamp of enrollments.0001_initial so we can
        # place the new record one second before it in chronological order.
        cursor.execute("""
            SELECT applied FROM django_migrations
            WHERE app = 'enrollments' AND name = '0001_initial'
        """)
        enrollments_date = cursor.fetchone()

        if not enrollments_date:
            print("[WARNING] Migration enrollments.0001_initial non trouvee")
            return

        # Subtract one second so the dependency ordering is correct.
        applied_date = enrollments_date[0] - timedelta(seconds=1)

        cursor.execute("""
            INSERT INTO django_migrations (app, name, applied)
            VALUES ('academic_sessions', '0001_initial', %s)
        """, [applied_date])

        print(f"[OK] Migration academic_sessions.0001_initial ajoutee avec date: {applied_date}")
        print("[OK] Historique des migrations corrige")


if __name__ == '__main__':
    try:
        fix_migration_history()
        print("\n[SUCCESS] Correction terminee. Vous pouvez maintenant executer: python manage.py migrate")
    except Exception as e:
        print(f"\n[ERROR] Erreur: {e}")
        import traceback
        traceback.print_exc()
