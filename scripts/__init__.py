"""
UniAbsences – scripts package.

This package contains all standalone maintenance, setup, and verification
scripts for the UniAbsences university attendance management system.

Sub-packages
------------
maintenance/
    Low-level database repair and schema inspection utilities.
setup/
    Data-seeding scripts used to populate the database with test and UAT
    fixtures across successive development iterations.
verify/
    Smoke-test scripts that exercise key business rules (at-risk detection,
    role separation, export generation, etc.) without running the full Django
    test suite.

Top-level helpers
-----------------
utils.py
    Single ``setup_django()`` helper consumed by every script in this tree to
    bootstrap the Django environment before importing models.
"""
