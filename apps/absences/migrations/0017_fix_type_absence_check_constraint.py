"""
Migration : corrige l'ancienne contrainte CHECK sur absence.type_absence.

L'ancienne contrainte « absence_type_absence_check » n'autorisait que HEURE,
SEANCE, JOURNEE. Après que la migration 0016 a converti toutes les données
en ABSENT/PARTIEL, les insertions avec les nouveaux types étaient rejetées
par PostgreSQL.

Cette migration supprime l'ancienne contrainte et la remplace par une qui
autorise les valeurs valides actuelles : ABSENT, PARTIEL, plus les valeurs
anciennes par sécurité.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("absences", "0016_update_type_absence_choices"),
    ]

    operations = [
        # Supprime l'ancienne contrainte
        migrations.RunSQL(
            sql='ALTER TABLE absence DROP CONSTRAINT IF EXISTS "absence_type_absence_check";',
            reverse_sql=migrations.RunSQL.noop,
        ),
        # Crée la nouvelle contrainte autorisant valeurs actuelles + anciennes
        migrations.RunSQL(
            sql="""
                ALTER TABLE absence ADD CONSTRAINT "absence_type_absence_check"
                CHECK (type_absence IN ('ABSENT', 'PARTIEL', 'HEURE', 'SEANCE', 'JOURNEE', 'RETARD'));
            """,
            reverse_sql='ALTER TABLE absence DROP CONSTRAINT IF EXISTS "absence_type_absence_check";',
        ),
    ]
