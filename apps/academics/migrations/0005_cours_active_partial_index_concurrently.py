from django.db import migrations, models


def forwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS cours_actif_299288_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS cours_code_active_idx "
            "ON cours (code_cours) WHERE actif IS TRUE;"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS cours_actif_299288_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS cours_code_active_idx "
            "ON cours (code_cours) WHERE actif = 1;"
        )


def backwards(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS cours_code_active_idx;")
        schema_editor.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS cours_actif_299288_idx "
            "ON cours (actif, code_cours);"
        )
    else:
        schema_editor.execute("DROP INDEX IF EXISTS cours_code_active_idx;")
        schema_editor.execute(
            "CREATE INDEX IF NOT EXISTS cours_actif_299288_idx "
            "ON cours (actif, code_cours);"
        )


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('academics', '0004_cours_cours_actif_299288_idx'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(forwards, backwards),
            ],
            state_operations=[
                migrations.RemoveIndex(
                    model_name='cours',
                    name='cours_actif_299288_idx',
                ),
                migrations.AddIndex(
                    model_name='cours',
                    index=models.Index(
                        fields=['code_cours'],
                        condition=models.Q(actif=True),
                        name='cours_code_active_idx',
                    ),
                ),
            ],
        ),
    ]
