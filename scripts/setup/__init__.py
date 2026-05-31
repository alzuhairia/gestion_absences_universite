"""
UniAbsences – scripts.setup package.

This sub-package contains data-seeding scripts used to populate the database
with realistic fixtures for development, iterative testing, and
User Acceptance Testing (UAT).

Each module is self-contained and idempotent where possible: running it
multiple times will not create duplicate records for entities that already
exist.

Modules
-------
setup_teacher.py
    Creates a professor user and assigns the INFO101 course to them.  Also
    creates a second unassigned course to verify teacher-visibility scoping.
setup_test_data.py
    Version 1 – initial fixture with one admin, one student, one course,
    and two absence records totalling 40 hours (threshold boundary).
setup_test_data_justif.py
    Adds a pending justification record for the student's first absence,
    extending the V1 dataset.
setup_test_data_v2.py
    Version 2 – fixes foreign-key field names and immediately creates a
    ``Justification`` alongside the second absence.
setup_test_data_v3.py
    Version 3 – adds the required ``id_annee`` field to ``Seance`` records
    and removes the invalid ``type_seance`` argument.
setup_test_data_v4.py
    Version 4 – cleaned-up final version used by the test suite and
    referenced by ``setup_teacher.py``.
setup_uat_data.py
    UAT fixture with multiple courses at different absence thresholds
    (green/orange/red), prerequisite relationships, and notifications.
"""

