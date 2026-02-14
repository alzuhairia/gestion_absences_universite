from django.db import migrations, models


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS utilisateur_nom_cecd3a_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS utilisateur_nom_prenom_idx "
            "ON utilisateur (nom, prenom);"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS utilisateur_nom_cecd3a_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS utilisateur_nom_prenom_idx "
            "ON utilisateur (nom, prenom);"
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS utilisateur_nom_prenom_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS utilisateur_nom_cecd3a_idx "
            "ON utilisateur (nom, prenom);"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS utilisateur_nom_prenom_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS utilisateur_nom_cecd3a_idx "
            "ON utilisateur (nom, prenom);"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('accounts', '0005_postgres_trgm_user_indexes'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(forwards, backwards),
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name='user',
                    name='utilisateur_nom_cecd3a_idx',
                ),
                migrations.AddIndex(
                    model_name='user',
                    index=models.Index(fields=['nom', 'prenom'], name='utilisateur_nom_prenom_idx'),
                ),
            ],
        ),
    ]
