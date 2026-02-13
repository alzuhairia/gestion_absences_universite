from django.db import migrations, DatabaseError


def _pg_trgm_available(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';")
        return cursor.fetchone() is not None


def create_postgres_trgm_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    if not _pg_trgm_available(schema_editor):
        try:
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except DatabaseError as exc:
            print(f"[accounts] pg_trgm extension unavailable, skipping trigram indexes: {exc}")
            return

    if not _pg_trgm_available(schema_editor):
        print("[accounts] pg_trgm extension unavailable, skipping trigram indexes.")
        return

    schema_editor.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS utilisateur_nom_trgm_gin_idx "
        "ON utilisateur USING GIN (nom gin_trgm_ops);"
    )
    schema_editor.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS utilisateur_prenom_trgm_gin_idx "
        "ON utilisateur USING GIN (prenom gin_trgm_ops);"
    )
    schema_editor.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS utilisateur_email_trgm_gin_idx "
        "ON utilisateur USING GIN (email gin_trgm_ops);"
    )


def drop_postgres_trgm_indexes(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS utilisateur_nom_trgm_gin_idx;")
    schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS utilisateur_prenom_trgm_gin_idx;")
    schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS utilisateur_email_trgm_gin_idx;")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('accounts', '0004_user_utilisateur_nom_cecd3a_idx'),
    ]

    operations = [
        migrations.RunPython(
            code=create_postgres_trgm_indexes,
            reverse_code=drop_postgres_trgm_indexes,
        ),
    ]
