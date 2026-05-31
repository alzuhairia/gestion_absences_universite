"""
UniAbsences – scripts.fix_student_enrollment
=============================================

One-shot repair script that re-enrols a specific student (Louis VANDERVEKEN)
in all active Level-2 courses for the current academic year.

Background
----------
After a data inconsistency was identified where the student's ``niveau``
field did not match their actual course enrolments, this script:

1. Updates the student's ``niveau`` attribute to 2.
2. Creates ``Inscription`` records for every active Level-2 course that
   belongs to the current academic year, skipping courses the student is
   already enrolled in.

The operation runs inside a single database transaction so that all
insertions either succeed together or are rolled back as a unit.

Usage
-----
Run from the project root after activating the virtual environment::

    python scripts/fix_student_enrollment.py

Exits with code 1 if the target student or active academic year cannot be
found, or if no Level-2 courses exist for that year.

Part of: UniAbsences maintenance / data repair layer.
"""

import os
import sys
import django

# Insert the project root so that Django settings and apps are importable.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User
from apps.academics.models import Cours
from apps.academic_sessions.models import AnneeAcademique
from apps.enrollments.models import Inscription
from django.db import transaction

# ---------------------------------------------------------------------------
# Step 1 – Locate the target student
# ---------------------------------------------------------------------------

student = User.objects.filter(email='louis.vanderveken@hainaut-promsoc.be').first()
if not student:
    print("Étudiant non trouvé")
    exit(1)

print(f"Étudiant trouvé: {student.get_full_name()}")
print(f"Niveau actuel: {student.niveau}")

# ---------------------------------------------------------------------------
# Step 2 – Locate the active academic year
# ---------------------------------------------------------------------------

active_year = AnneeAcademique.objects.filter(active=True).first()
if not active_year:
    print("Aucune année académique active trouvée")
    exit(1)

print(f"Année académique active: {active_year.libelle}")

# ---------------------------------------------------------------------------
# Step 3 – Retrieve Level-2 courses for this academic year
# ---------------------------------------------------------------------------

niveau = 2
level_courses = Cours.objects.filter(
    niveau=niveau,
    id_annee=active_year,
    actif=True
)

print(f"\nCours trouvés pour le niveau {niveau}: {level_courses.count()}")
for course in level_courses:
    print(f"  - {course.code_cours}: {course.nom_cours}")

if not level_courses.exists():
    print("\nAucun cours trouvé. Vérifiez que les cours ont bien le niveau 2 et l'année académique assignée.")
    exit(1)

# ---------------------------------------------------------------------------
# Step 4 – Update the student's level
# ---------------------------------------------------------------------------

# Synchronise the User.niveau field with the target academic level so that
# automatic enrollment logic (if any) remains consistent.
student.niveau = niveau
student.save()
print(f"\nNiveau de l'étudiant mis à jour à {niveau}")

# ---------------------------------------------------------------------------
# Step 5 – Create missing enrolment records atomically
# ---------------------------------------------------------------------------

enrolled_count = 0
skipped_count = 0

with transaction.atomic():
    for course in level_courses:
        # Skip courses the student is already enrolled in to preserve any
        # existing status or metadata.
        if Inscription.objects.filter(
            id_etudiant=student,
            id_cours=course,
            id_annee=active_year
        ).exists():
            print(f"  [*] Deja inscrit a {course.code_cours}")
            skipped_count += 1
            continue

        # Create a fresh enrolment with standard defaults.
        Inscription.objects.create(
            id_etudiant=student,
            id_cours=course,
            id_annee=active_year,
            type_inscription='NORMALE',
            eligible_examen=True,
            status='EN_COURS'
        )
        print(f"  [+] Inscrit a {course.code_cours}")
        enrolled_count += 1

print(f"\nRésultat:")
print(f"  - {enrolled_count} nouvelle(s) inscription(s) créée(s)")
print(f"  - {skipped_count} inscription(s) déjà existante(s)")

# ---------------------------------------------------------------------------
# Step 6 – Post-repair summary
# ---------------------------------------------------------------------------

total_inscriptions = Inscription.objects.filter(id_etudiant=student).count()
print(f"\nTotal inscriptions pour cet étudiant: {total_inscriptions}")
