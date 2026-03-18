"""
Migration: Fix the legacy CHECK constraint on absence.type_absence.

The old constraint 'absence_type_absence_check' only allowed HEURE, SEANCE, JOURNEE.
After migration 0016 converted all data to ABSENT/PARTIEL, inserts with the new
types were rejected by PostgreSQL.

This migration drops the legacy constraint and replaces it with one that allows
the current valid values: ABSENT, PARTIEL, plus legacy values for safety.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("absences", "0016_update_type_absence_choices"),
    ]

    operations = [
        # Drop the legacy constraint
        migrations.RunSQL(
            sql='ALTER TABLE absence DROP CONSTRAINT IF EXISTS "absence_type_absence_check";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Create new constraint allowing current + legacy values
        migrations.RunSQL(
            sql="""
                ALTER TABLE absence ADD CONSTRAINT "absence_type_absence_check"
                CHECK (type_absence IN ('ABSENT', 'PARTIEL', 'HEURE', 'SEANCE', 'JOURNEE', 'RETARD'));
            """,
            reverse_sql='ALTER TABLE absence DROP CONSTRAINT IF EXISTS "absence_type_absence_check";',
        ),
    ]
