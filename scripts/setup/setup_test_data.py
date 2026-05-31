"""
UniAbsences – scripts.setup.setup_test_data
============================================

Version 1 data-seeding script.  Creates a minimal but functional fixture
with one admin, one student, one course, and two absence records that place
the student exactly at the 40 % threshold (danger zone).

Note: This version uses the legacy ``annee_academique`` string field on
``Inscription`` instead of the ``id_annee`` FK.  Superseded by
``setup_test_data_v2.py`` which uses the correct foreign key.

What this script creates
------------------------
* **Admin** – ``admin@uni.edu`` / ``adminpassword``
* **Student** – ``alex.student@uni.edu`` / ``studentpassword`` (ETUDIANT)
* **Faculty / Department / Course** – Sciences > Informatique > INFO101
  (100 total hours, 40 % threshold)
* **Enrollment** – student enrolled in INFO101
* **Two absences** – each 20 h, totalling 40 h = 40 % → RED status

Usage
-----
::

    python scripts/setup/setup_test_data.py

Part of: UniAbsences setup / test-data seeding layer (v1).
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
from apps.academic_sessions.models import Seance
from apps.absences.models import Absence
from django.utils import timezone
from datetime import timedelta


def create_test_data() -> None:
    """Seed the V1 test dataset.

    Creates users, the academic hierarchy, an enrollment, two sessions, and
    two unjustified absences.  Skips absence creation if absences already
    exist for the enrollment.
    """
    print("Creating test data...")

    # ------------------------------------------------------------------
    # Step 1 – Users
    # ------------------------------------------------------------------
    admin_email = "admin@uni.edu"
    if not User.objects.filter(email=admin_email).exists():
        admin = User.objects.create_superuser(
            email=admin_email,
            nom="Admin",
            prenom="Super",
            password="adminpassword"
        )
        print(f"Created Admin: {admin_email}")
    else:
        print(f"Admin already exists: {admin_email}")

    student_email = "alex.student@uni.edu"
    if not User.objects.filter(email=student_email).exists():
        student = User.objects.create_user(
            email=student_email,
            nom="Student",
            prenom="Alex",
            password="studentpassword",
            role=User.Role.ETUDIANT
        )
        print(f"Created Student: {student_email}")
    else:
        print(f"Student already exists: {student_email}")
        student = User.objects.get(email=student_email)

    # ------------------------------------------------------------------
    # Step 2 – Academic hierarchy
    # ------------------------------------------------------------------
    faculte, _ = Faculte.objects.get_or_create(nom_faculte="Sciences")
    departement, _ = Departement.objects.get_or_create(
        nom_departement="Informatique",
        defaults={'id_faculte': faculte}
    )

    cours, _ = Cours.objects.get_or_create(
        code_cours="INFO101",
        defaults={
            'nom_cours': "Introduction to Python & Django",
            'nombre_total_periodes': 100,
            'seuil_absence': 40,
            'id_departement': departement
        }
    )
    print(f"Course: {cours.nom_cours}")

    # ------------------------------------------------------------------
    # Step 3 – Enrollment
    # Note: V1 uses the legacy string field ``annee_academique`` rather than
    # the ``id_annee`` FK introduced in later versions.
    # ------------------------------------------------------------------
    inscription, _ = Inscription.objects.get_or_create(
        id_etudiant=student,
        id_cours=cours,
        defaults={'annee_academique': "2024-2025"}
    )
    print("Enrollment ensure.")

    # ------------------------------------------------------------------
    # Step 4 – Sessions and absences
    # Create two 20-hour absences so the student reaches exactly 40 h out
    # of 100 h total (= 40 % → RED / danger threshold).
    # ------------------------------------------------------------------
    current_absences = Absence.objects.filter(id_inscription=inscription).count()
    if current_absences == 0:
        base_time = timezone.now()

        # Session 1: a lecture (CM) – student recorded 20 h absent.
        seance1 = Seance.objects.create(
            id_cours=cours,
            date_seance=base_time.date(),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time(),
            type_seance="CM"
        )
        Absence.objects.create(
            id_inscription=inscription,
            id_seance=seance1,
            duree_absence=20.0,  # 20 h of the 100 h total
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first()  # Assign to any existing user
        )

        # Session 2: a practical (TP) – another 20 h, reaching 40 h total.
        seance2 = Seance.objects.create(
            id_cours=cours,
            date_seance=base_time.date() + timedelta(days=1),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time(),
            type_seance="TP"
        )
        abs_to_justify = Absence.objects.create(
            id_inscription=inscription,
            id_seance=seance2,
            duree_absence=20.0,
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first()
        )
        print(f"Created 40h of absences. Student should be at 40% (Red).")
        print(f"Absence to justify ID: {abs_to_justify.id_absence}")

    else:
        print("Absences already exist, skipping creation.")


if __name__ == "__main__":
    create_test_data()
