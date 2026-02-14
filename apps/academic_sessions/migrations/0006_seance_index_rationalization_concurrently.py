from django.db import migrations, models


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS seance_id_cour_e986d8_idx;")
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS seance_cours_annee_date_heure_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS seance_cours_annee_dt_h_idx "
            "ON seance (id_cours, id_annee, date_seance, heure_debut);"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS seance_id_cour_e986d8_idx;")
        schema_editor.execute("DROP INDEX IF EXISTS seance_cours_annee_date_heure_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS seance_cours_annee_dt_h_idx "
            "ON seance (id_cours, id_annee, date_seance, heure_debut);"
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS seance_cours_annee_dt_h_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS seance_id_cour_e986d8_idx "
            "ON seance (id_cours, id_annee, date_seance);"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS seance_cours_annee_dt_h_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS seance_id_cour_e986d8_idx "
            "ON seance (id_cours, id_annee, date_seance);"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('academic_sessions', '0005_seance_seance_id_cour_e986d8_idx'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(forwards, backwards),
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name='seance',
                    name='seance_id_cour_e986d8_idx',
                ),
                migrations.AddIndex(
                    model_name='seance',
                    index=models.Index(
                        fields=['id_cours', 'id_annee', 'date_seance', 'heure_debut'],
                        name='seance_cours_annee_dt_h_idx',
                    ),
                ),
            ],
        ),
    ]
