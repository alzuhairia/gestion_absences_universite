import re
from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import connection, transaction


class Command(BaseCommand):
    help = "Batch migrate justification document BLOBs to FileField storage."

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=200)
        parser.add_argument("--start-id", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--model", default="absences.Justification")
        parser.add_argument("--table", default="")
        parser.add_argument("--source-column", default="document")
        parser.add_argument("--target-column", default="document_file")
        parser.add_argument("--pk-column", default="")
        parser.add_argument("--dry-run", action="store_true")

    def _validate_identifier(self, name, label):
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
            raise ValueError(f"Invalid {label}: {name}")

    def _get_model(self, model_label):
        try:
            return django_apps.get_model(model_label)
        except Exception as exc:
            raise ValueError(f"Invalid model label: {model_label}") from exc

    def _resolve_column(self, model, name, label):
        if not name:
            raise ValueError(f"Missing {label}")
        try:
            field = model._meta.get_field(name)
            return field.column
        except FieldDoesNotExist:
            return name

    def _assert_column_exists(self, table, column):
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = %s AND column_name = %s
                """,
                [table, column],
            )
            if cursor.fetchone() is None:
                raise ValueError(
                    f"Column '{column}' not found on table '{table}'. "
                    "Run migration 0003 first and execute this command before 0004."
                )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        start_id = options["start_id"]
        limit = options["limit"]
        model_label = options["model"]
        table = options["table"]
        source_col = options["source_column"]
        target_col = options["target_column"]
        pk_col = options["pk_column"]
        dry_run = options["dry_run"]

        model = self._get_model(model_label)
        if not table:
            table = model._meta.db_table
        if not pk_col:
            pk_col = model._meta.pk.column

        source_col = self._resolve_column(model, source_col, "source column/field")
        target_col = self._resolve_column(model, target_col, "target column/field")

        self._validate_identifier(table, "table")
        self._validate_identifier(source_col, "source column")
        self._validate_identifier(target_col, "target column")
        self._validate_identifier(pk_col, "pk column")
        self._assert_column_exists(table, source_col)
        self._assert_column_exists(table, target_col)

        total_migrated = 0
        last_id = start_id

        self.stdout.write(
            f"Starting batch migration: model={model_label}, table={table}, source={source_col}, "
            f"target={target_col}, pk={pk_col}, batch_size={batch_size}, "
            f"start_id={start_id}, limit={limit}, dry_run={dry_run}"
        )

        while True:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT {pk_col}, {source_col}
                    FROM {table}
                    WHERE {pk_col} > %s
                      AND {source_col} IS NOT NULL
                      AND ({target_col} IS NULL OR {target_col} = '')
                    ORDER BY {pk_col}
                    LIMIT %s
                    """,
                    [last_id, batch_size],
                )
                rows = cursor.fetchall()

            if not rows:
                break

            for pk_value, data in rows:
                last_id = pk_value
                if data is None:
                    continue
                if hasattr(data, "tobytes"):
                    data = data.tobytes()
                if not data:
                    continue

                filename = f"justifications/justification_{pk_value}.bin"
                saved_name = filename
                if not dry_run:
                    saved_name = default_storage.save(filename, ContentFile(data))

                if not dry_run:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                f"""
                                UPDATE {table}
                                SET {target_col} = %s
                                WHERE {pk_col} = %s
                                """,
                                [saved_name, pk_value],
                            )

                total_migrated += 1
                if limit and total_migrated >= limit:
                    self.stdout.write("Reached limit, stopping.")
                    return

            self.stdout.write(f"Migrated so far: {total_migrated}")

        self.stdout.write(f"Done. Total migrated: {total_migrated}")
