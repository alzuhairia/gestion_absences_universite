"""
UniAbsences – scripts.debug_enrollments
========================================

Diagnostic script that inspects course and enrollment data stored in the
database and prints a structured report to stdout.

Checks performed
----------------
1. Total number of active courses.
2. Active courses broken down by academic level (1, 2, 3) with their
   associated academic year.
3. Active courses grouped by academic year.
4. Active courses that are **missing** an academic year (data integrity
   issue).
5. Total enrollment counts and counts filtered to ``EN_COURS`` status.
6. Enrollments for the currently active academic year.
7. Detailed enrollment summary for a specific student
   (louis.vanderveken@hainaut-promsoc.be) used during development.

Intended use
------------
Run directly from the shell after the Django environment is configured::

    python scripts/debug_enrollments.py

Part of: UniAbsences maintenance / debug layer.
"""

import os
import sys
import django

# Insert the project root into sys.path so that ``config.settings`` and all
# application modules can be imported without installation.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription

# ---------------------------------------------------------------------------
# Section 1 – Course verification
# ---------------------------------------------------------------------------

print("=== COURSE VERIFICATION ===")
print(f"\nTotal active courses: {Cours.objects.filter(actif=True).count()}")

print("\nCourses by level:")
for n in [1, 2, 3]:
    # Fetch all active courses at this academic level.
    c = Cours.objects.filter(niveau=n, actif=True)
    print(f"  Level {n}: {c.count()} courses")
    for course in c:
        # Display the academic year label, or "NULL" when the FK is unset.
        year_str = course.id_annee.libelle if course.id_annee else "NULL"
        print(f"    - {course.code_cours}: year={year_str}")

print("\nCourses by academic year:")
for y in AnneeAcademique.objects.all():
    c = Cours.objects.filter(id_annee=y, actif=True)
    print(f"  {y.libelle} (active={y.active}): {c.count()} courses")

# Courses with a NULL academic year are a data integrity problem – they will
# not be matched by enrollment queries that filter on id_annee.
print("\nCourses without academic year:")
c = Cours.objects.filter(id_annee__isnull=True, actif=True)
print(f"  {c.count()} courses")
for course in c:
    print(f"    - {course.code_cours} (level={course.niveau})")

# ---------------------------------------------------------------------------
# Section 2 – Enrollment verification
# ---------------------------------------------------------------------------

print("\n=== ENROLLMENT VERIFICATION ===")
print(f"\nTotal enrollments: {Inscription.objects.count()}")
print(f"EN_COURS enrollments: {Inscription.objects.filter(status='EN_COURS').count()}")

# Narrow down to the currently active academic year.
active_year = AnneeAcademique.objects.filter(active=True).first()
if active_year:
    print(f"\nEnrollments for active year ({active_year.libelle}):")
    inscriptions = Inscription.objects.filter(id_annee=active_year, status='EN_COURS')
    print(f"  {inscriptions.count()} enrollments")
    for ins in inscriptions:
        print(f"    - {ins.id_etudiant.get_full_name()} -> {ins.id_cours.code_cours} (niveau={ins.id_cours.niveau})")
else:
    print("\nAucune année académique active trouvée")

# ---------------------------------------------------------------------------
# Section 3 – Per-student verification (development fixture student)
# ---------------------------------------------------------------------------

print("\n=== VÉRIFICATION DE L'ÉTUDIANT ===")
student = User.objects.filter(email='louis.vanderveken@hainaut-promsoc.be').first()
if student:
    print(f"\nÉtudiant trouvé: {student.get_full_name()}")
    print(f"  Niveau: {student.niveau}")
    print(f"  Inscriptions: {Inscription.objects.filter(id_etudiant=student).count()}")
    for ins in Inscription.objects.filter(id_etudiant=student):
        print(f"    - {ins.id_cours.code_cours} (année={ins.id_annee.libelle}, statut={ins.status})")
else:
    print("\nÉtudiant non trouvé")
