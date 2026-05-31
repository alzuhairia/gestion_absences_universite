"""
UniAbsences – scripts.maintenance package.

This sub-package groups low-level database maintenance utilities for the
UniAbsences system.  Each module addresses a specific operational concern
that cannot be resolved through Django management commands alone.

Modules
-------
check_schema.py
    Inspect a SQLite database file directly (without Django) to confirm
    whether a given column exists in a given table.
check_schema_django.py
    Same check but performed through Django's database connection, making it
    compatible with PostgreSQL and other backends.
create_system_settings_table.py
    Idempotent DDL script that creates the ``system_settings`` table if it
    does not yet exist (used after faking a migration).
fix_migrations.py
    Patches the ``django_migrations`` table to insert a missing
    ``academic_sessions.0001_initial`` entry before running ``migrate``.
force_add_column.py
    Emergency DDL fallback that adds the ``state`` column to the
    ``justification`` table via raw SQL when the migration cannot be applied
    normally.
reproduce_issue.py
    Minimal reproduction harness that exercises the ``download_report_pdf``
    view for a specific UAT user to capture tracebacks.
reset_messaging_db.py
    Drops the ``message`` table and clears the messaging app's migration
    history so that ``migrate`` can recreate it from scratch.
"""

