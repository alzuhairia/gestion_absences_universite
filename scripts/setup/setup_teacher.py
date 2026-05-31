"""
UniAbsences – scripts.setup.setup_teacher
==========================================

Seeds the database with a professor user and assigns the INFO101 course to
that professor for testing teacher-specific dashboard behaviour.

What this script creates
------------------------
1. **Professor** – ``alan.turing@uni.edu`` / ``profpassword`` with the
   ``PROFESSEUR`` role.
2. **Course assignment** – the existing ``INFO101`` course is linked to the
   professor.  Run ``setup_test_data_v4.py`` first to ensure INFO101 exists.
3. **Unassigned course** – ``MATH101`` is created (or left unchanged) without
   a professor so that tests can verify the professor only sees their own
   courses.

Prerequisites
-------------
``setup_test_data_v4.py`` must have been run beforehand so that the INFO101
course and the ``Informatique`` department already exist.

Usage
-----
::

    python scripts/setup/setup_teacher.py

Part of: UniAbsences setup / test-data seeding layer.
"""

import os
import sys
from pathlib import Path

# Bootstrap Django before any app imports.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import Seance, AnneeAcademique
from apps.absences.models import Absence, Justification
from django.utils import timezone


def create_teacher_test_data() -> None:
    """Seed the professor and related course data.

    Steps
    -----
    1. Create (or locate) the professor account.
    2. Assign INFO101 to the professor.
    3. Create MATH101 without a professor to serve as a negative test case.
    """
    print("Creating TEACHER test data...")

    # ------------------------------------------------------------------
    # Step 1 – Create the professor account
    # ------------------------------------------------------------------
    prof_email = "alan.turing@uni.edu"
    if not User.objects.filter(email=prof_email).exists():
        prof = User.objects.create_user(
            email=prof_email,
            nom="Turing",
            prenom="Alan",
            password="profpassword",
            role=User.Role.PROFESSEUR
        )
        print(f"Created Professor: {prof_email}")
    else:
        print(f"Professor already exists: {prof_email}")
        prof = User.objects.get(email=prof_email)

    # ------------------------------------------------------------------
    # Step 2 – Assign the INFO101 course to the professor
    # ------------------------------------------------------------------
    try:
        cours = Cours.objects.get(code_cours="INFO101")
        cours.professeur = prof
        cours.save()
        print(f"Assigned {cours} to {prof}")
    except Cours.DoesNotExist:
        print("Error: INFO101 course not found. Run setup_test_data_v4.py first.")

    # ------------------------------------------------------------------
    # Step 3 – Create an unassigned course for visibility testing
    # ------------------------------------------------------------------
    # Ensure the required department hierarchy exists before creating the course.
    faculte, _ = Faculte.objects.get_or_create(nom_faculte="Sciences")
    departement, _ = Departement.objects.get_or_create(
        nom_departement="Informatique",
        defaults={'id_faculte': faculte}
    )

    # This course intentionally has no professor assigned so that dashboard
    # visibility tests can confirm professors only see their own courses.
    cours_other, created = Cours.objects.get_or_create(
        code_cours="MATH101",
        defaults={
            'nom_cours': "Mathematics for CS",
            'nombre_total_periodes': 60,
            'seuil_absence': 40,
            'id_departement': departement
        }
    )
    if created:
        print(f"Created other course: {cours_other} (No Professor)")


if __name__ == "__main__":
    create_teacher_test_data()
