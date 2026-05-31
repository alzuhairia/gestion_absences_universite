"""
Management Command: migrate_justification_documents
— apps/absences/management/commands/migrate_justification_documents.py

Part of the UniAbsences university attendance management system.

This one-shot data-migration command copies justification document BLOBs that
were stored in a binary database column into Django's ``FileField``-backed
file storage (typically the local filesystem or an object-store backend).

It is designed to be idempotent: rows whose target column is already populated
are skipped, so the command can be safely re-run after a partial failure.

Intended execution window:
    Run this command AFTER applying migration 0003 (which adds the target
    FileField column) and BEFORE applying migration 0004 (which drops the
    legacy BLOB column).  The command validates that both columns exist before
    processing any rows and aborts with a clear error message otherwise.

Usage::

    # Migrate all records in the default Justification model, 200 at a time:
    python manage.py migrate_justification_documents

    # Preview what would be migrated without writing anything:
    python manage.py migrate_justification_documents --dry-run

    # Use a smaller batch, starting from a specific primary key:
    python manage.py migrate_justification_documents --batch-size 50 --start-id 1000

    # Stop after migrating 500 records:
    python manage.py migrate_justification_documents --limit 500

    # Target a different model or column layout:
    python manage.py migrate_justification_documents \\
        --model absences.Justification \\
        --source-column document \\
        --target-column document_file
"""
import re
from typing import cast

from django.apps import apps as django_apps
from django.core.exceptions import FieldDoesNotExist
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from django.db.models import Field, Model


class Command(BaseCommand):
    """
    Django management command that batch-migrates justification document BLOBs
    to ``FileField`` storage.

    The migration is performed in configurable batches using keyset pagination
    (``WHERE pk > last_id ORDER BY pk LIMIT batch_size``) to avoid loading the
    entire table into memory.  Each row is processed atomically: the file is
    written to storage and the database column is updated in the same
    ``transaction.atomic()`` block so that a partial failure leaves the row in
    a consistent (source-populated, target-empty) state that will be retried on
    the next run.

    Attributes:
        help (str): Short description shown by ``manage.py help migrate_justification_documents``.
    """

    help = "Batch migrate justification document BLOBs to FileField storage."

    def add_arguments(self, parser):
        """
        Register all command-line arguments.

        Args:
            parser (argparse.ArgumentParser): the argument parser provided by
                Django's management framework.
        """
        parser.add_argument("--batch-size", type=int, default=200,
                            help="Number of rows to process per database query (default: 200).")
        parser.add_argument("--start-id", type=int, default=0,
                            help="Primary key value to start from; rows with pk <= start-id are skipped.")
        parser.add_argument("--limit", type=int, default=0,
                            help="Stop after migrating this many rows (0 = no limit).")
        parser.add_argument("--model", default="absences.Justification",
                            help="Django app_label.ModelName of the model to migrate (default: absences.Justification).")
        parser.add_argument("--table", default="",
                            help="Override the database table name (defaults to the model's db_table).")
        parser.add_argument("--source-column", default="document",
                            help="Model field name or raw column name holding the BLOB data.")
        parser.add_argument("--target-column", default="document_file",
                            help="Model field name or raw column name for the FileField path.")
        parser.add_argument("--pk-column", default="",
                            help="Override the primary key column name (defaults to the model's pk column).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Print what would be migrated without writing files or updating the database.")

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_identifier(self, name, label):
        """
        Validate that a table or column identifier contains only safe characters.

        Only identifiers matching ``^[A-Za-z_][A-Za-z0-9_]*$`` are accepted.
        This prevents SQL injection through the raw-SQL queries used for keyset
        pagination, where Django's parameterisation cannot protect identifiers.

        Args:
            name (str | None): the identifier string to validate.
            label (str): human-readable label used in the error message.

        Raises:
            ValueError: if ``name`` does not match the safe identifier pattern.
        """
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name or ""):
            raise ValueError(f"Invalid {label}: {name}")

    def _get_model(self, model_label):
        """
        Resolve a Django ``app_label.ModelName`` string to a model class.

        Args:
            model_label (str): fully-qualified model label
                (e.g. ``"absences.Justification"``).

        Returns:
            type[Model]: the resolved Django model class.

        Raises:
            ValueError: if the label cannot be resolved (app not installed or
                model does not exist).
        """
        try:
            return django_apps.get_model(model_label)
        except Exception as exc:
            raise ValueError(f"Invalid model label: {model_label}") from exc

    def _resolve_column(self, model: type[Model], name: str, label: str) -> str:
        """
        Resolve a model field name to its underlying database column name.

        If ``name`` matches a model field, the field's ``column`` attribute is
        returned (which may differ from the field name when ``db_column`` is
        set).  If the field is not found, ``name`` is returned as-is, allowing
        callers to pass raw column names directly.

        Args:
            model (type[Model]): Django model class to inspect.
            name (str): field name or raw column name to resolve.
            label (str): human-readable label used in the error message when
                ``name`` is empty.

        Returns:
            str: the resolved database column name.

        Raises:
            ValueError: if ``name`` is an empty string.
        """
        if not name:
            raise ValueError(f"Missing {label}")
        try:
            field = cast(Field, model._meta.get_field(name))
        except FieldDoesNotExist:
            # Treat as a raw column name and let the SQL validation catch issues.
            return name
        return field.column

    def _assert_column_exists(self, table, column):
        """
        Verify that a column exists on the given database table.

        Queries ``information_schema.columns`` to confirm the column is present
        before the batch loop begins.  This provides an early, actionable error
        message instead of a cryptic SQL error mid-migration.

        Args:
            table (str): database table name.
            column (str): column name to check.

        Raises:
            ValueError: if the column is not found on the table, with a hint
                pointing to the migration that must be applied first.
        """
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

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        """
        Execute the batch BLOB-to-file migration.

        Steps:
          1. Resolve and validate all inputs (model, table, column names).
          2. Confirm both source and target columns exist in the database.
          3. Iterate in batches using keyset pagination:
               a. Fetch up to ``batch_size`` rows with a populated source column
                  and an empty target column.
               b. For each row, save the BLOB bytes to ``default_storage``.
               c. Update the target column with the saved file path in an
                  atomic transaction.
          4. Stop when no rows remain or ``--limit`` is reached.

        Args:
            *args: positional arguments (unused; required by the base class).
            **options (dict): parsed command options.  See ``add_arguments``
                for the full list of accepted keys.

        Side effects:
            - Writes files to ``default_storage``.
            - Updates the target column for each migrated row.
            - Prints progress and a final summary to ``self.stdout``.
        """
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

        # Default the table name to the model's own db_table if not overridden.
        if not table:
            table = model._meta.db_table

        # Default the pk column to the model's primary key field column.
        if not pk_col:
            pk_field = model._meta.pk
            assert pk_field is not None
            pk_col = pk_field.column

        # Resolve field names to underlying DB column names.
        source_col = self._resolve_column(model, source_col, "source column/field")
        target_col = self._resolve_column(model, target_col, "target column/field")

        # Validate that all identifiers are safe before embedding them in SQL.
        self._validate_identifier(table, "table")
        self._validate_identifier(source_col, "source column")
        self._validate_identifier(target_col, "target column")
        self._validate_identifier(pk_col, "pk column")

        # Pre-flight check: confirm both columns actually exist in the schema.
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
            # Keyset pagination: fetch the next batch of rows whose BLOB column is
            # populated and whose FileField column has not yet been populated.
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
                    """,  # nosec B608 — identifiers are validated above
                    [last_id, batch_size],
                )
                rows = cursor.fetchall()

            # No more rows to process — migration is complete.
            if not rows:
                break

            for pk_value, data in rows:
                last_id = pk_value

                if data is None:
                    continue

                # Handle memoryview objects returned by some database backends (e.g. psycopg2).
                if hasattr(data, "tobytes"):
                    data = data.tobytes()

                if not data:
                    continue

                # Construct a deterministic filename based on the row's primary key.
                filename = f"justifications/justification_{pk_value}.bin"
                saved_name = filename

                if not dry_run:
                    # Save BLOB bytes to the configured file storage backend.
                    saved_name = default_storage.save(filename, ContentFile(data))

                if not dry_run:
                    # Update the FileField column atomically with the saved path.
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute(
                                f"""
                                UPDATE {table}
                                SET {target_col} = %s
                                WHERE {pk_col} = %s
                                """,  # nosec B608 — identifiers are validated above
                                [saved_name, pk_value],
                            )

                total_migrated += 1

                # Respect the --limit flag if set.
                if limit and total_migrated >= limit:
                    self.stdout.write("Reached limit, stopping.")
                    return

            self.stdout.write(f"Migrated so far: {total_migrated}")

        self.stdout.write(f"Done. Total migrated: {total_migrated}")
