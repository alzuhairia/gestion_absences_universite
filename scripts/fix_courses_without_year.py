"""
UniAbsences – scripts.fix_courses_without_year
===============================================

One-shot repair script that assigns the currently active academic year to
any active course whose ``id_annee`` foreign key is NULL.

Background
----------
Courses that lack an academic year are effectively invisible to enrollment
queries that filter on ``id_annee``, which causes students to appear
unenrolled even when enrollment records exist.  This script automates the
fix by bulk-updating all orphan courses with the active year in a single
database statement.

Usage
-----
Run from the project root after activating the virtual environment::

    python scripts/fix_courses_without_year.py

The script exits with code 1 if no active academic year is found, so it can
be used safely in automated pipelines.

Part of: UniAbsences maintenance / data repair layer.
"""

import os
import sys
import django

# Insert the project root so that Django settings and apps are importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique

# ---------------------------------------------------------------------------
# Step 1 – Locate the active academic year
# ---------------------------------------------------------------------------

# Only one academic year should be flagged as active at any given time.
# If none is found, abort early to avoid mis-assigning courses.
active_year = AnneeAcademique.objects.filter(active=True).first()
if not active_year:
    print("Aucune annee academique active trouvee")
    exit(1)

print(f"Annee academique active: {active_year.libelle}")

# ---------------------------------------------------------------------------
# Step 2 – Identify orphan courses
# ---------------------------------------------------------------------------

# A course is "orphan" here if it is active but has no academic year FK set.
courses_without_year = Cours.objects.filter(id_annee__isnull=True, actif=True)

print(f"\nCours sans annee academique: {courses_without_year.count()}")

# ---------------------------------------------------------------------------
# Step 3 – Patch orphan courses
# ---------------------------------------------------------------------------

if courses_without_year.exists():
    print("\nCours a corriger:")
    for course in courses_without_year:
        print(f"  - {course.code_cours} (niveau={course.niveau})")

    # Use a queryset bulk-update for efficiency (single SQL UPDATE statement).
    updated = courses_without_year.update(id_annee=active_year)
    print(f"\n{updated} cours mis a jour avec l'annee academique {active_year.libelle}")
else:
    print("\nAucun cours a corriger")
