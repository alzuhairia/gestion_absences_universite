from django.db import migrations, DatabaseError


def _pg_trgm_available(schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm';")
        return cursor.fetchone() is not None


def create_postgres_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    if not _pg_trgm_available(schema_editor):
        try:
            schema_editor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")
        except DatabaseError as exc:
            print(f"[audits] pg_trgm extension unavailable, skipping trigram index: {exc}")
            return
    if not _pg_trgm_available(schema_editor):
        print("[audits] pg_trgm extension unavailable, skipping trigram index.")
        return

    schema_editor.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS log_audit_action_trgm_gin_idx "
        "ON log_audit USING GIN (action gin_trgm_ops);"
    )


def drop_postgres_trgm_index(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return

    schema_editor.execute("DROP INDEX CONCURRENTLY IF EXISTS log_audit_action_trgm_gin_idx;")


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('audits', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(
            code=create_postgres_trgm_index,
            reverse_code=drop_postgres_trgm_index,
        ),
    ]
