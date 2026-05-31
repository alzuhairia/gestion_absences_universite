"""
UniAbsences – scripts.setup.setup_test_data_v2
===============================================

Version 2 data-seeding script.  Corrects the FK field names used in V1 and
immediately creates a ``Justification`` alongside the second absence so the
justification workflow can be tested without running an additional script.

Key differences from V1
-----------------------
* Uses ``id_annee`` (FK to ``AnneeAcademique``) on ``Inscription`` instead of
  the legacy ``annee_academique`` string field.
* Creates an ``AnneeAcademique`` record with ``code_annee="2024-2025"``.
* The second absence is created with status ``EN_ATTENTE`` and an associated
  ``Justification`` object in a single pass.
* If absences already exist but no ``EN_ATTENTE`` record is present, the
  script promotes the last absence and adds the missing justification.

What this script creates
------------------------
* **Admin** – ``admin@uni.edu`` / ``adminpassword``
* **Student** – ``alex.student@uni.edu`` / ``studentpassword`` (ETUDIANT)
* **Academic hierarchy** – Sciences > Informatique > INFO101
* **Academic year** – ``2024-2025`` (active)
* **Enrollment** – student enrolled in INFO101 for 2024-2025
* **Two absences + one justification** – 20 h each, 40 h total

Usage
-----
::

    python scripts/setup/setup_test_data_v2.py

Part of: UniAbsences setup / test-data seeding layer (v2).
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

from datetime import date
from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import Seance, AnneeAcademique
from apps.absences.models import Absence, Justification
from django.utils import timezone
from datetime import timedelta


def create_test_data() -> None:
    """Seed the V2 test dataset with correct FK references.

    Creates or retrieves all required records and ensures at least one
    ``EN_ATTENTE`` justification exists for the student's enrollment.
    """
    print("Creating test data with CORRECT Foreign Keys...")

    # ------------------------------------------------------------------
    # Step 1 – Users
    # ------------------------------------------------------------------
    admin_email = "admin@uni.edu"
    if not User.objects.filter(email=admin_email).exists():
        User.objects.create_superuser(
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

    # V2 fix: create the AcademicYear using the ``code_annee`` field (the
    # model uses ``code_annee`` as the unique lookup key in this version).
    annee, _ = AnneeAcademique.objects.get_or_create(
        code_annee="2024-2025",
        defaults={
            'date_debut': date(2024, 9, 1),
            'date_fin': date(2025, 6, 30),
            'active': True
        }
    )

    # ------------------------------------------------------------------
    # Step 3 – Enrollment
    # V2 fix: use the ``id_annee`` FK instead of the legacy string field.
    # ------------------------------------------------------------------
    inscription, created = Inscription.objects.get_or_create(
        id_etudiant=student,
        id_cours=cours,
        id_annee=annee,
        defaults={'eligible_examen': True}
    )
    print(f"Enrollment {'created' if created else 'exists'}: {inscription}")

    # ------------------------------------------------------------------
    # Step 4 – Sessions and absences
    # ------------------------------------------------------------------
    current_absences = Absence.objects.filter(id_inscription=inscription).count()
    if current_absences == 0:
        base_time = timezone.now()

        # Session 1 – 20 h unjustified absence.
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
            duree_absence=20.0,
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first()
        )

        # Session 2 – 20 h, created as EN_ATTENTE so a justification can be
        # attached immediately in the same pass.
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
            statut='EN_ATTENTE',
            encodee_par=User.objects.first()
        )

        # Create the justification record for the pending absence.
        Justification.objects.create(
            id_absence=abs_to_justify,
            document=b"fake_pdf_content",
            commentaire="Created by Setup V2",
            validee=False
        )

        print("Created Absences and Pending Justification.")

    else:
        print("Absences already exist.")
        # Ensure at least one absence with a pending justification exists so
        # the justification workflow view has data to display.
        pending = Absence.objects.filter(
            id_inscription=inscription, statut='EN_ATTENTE'
        ).exists()
        if not pending:
            last_abs = Absence.objects.filter(id_inscription=inscription).last()
            if last_abs:
                last_abs.statut = 'EN_ATTENTE'
                last_abs.save()
                Justification.objects.create(
                    id_absence=last_abs,
                    document=b"fake_pdf_content",
                    commentaire="Added by Setup V2 Update",
                    validee=False
                )
                print("Added missing justification.")


if __name__ == "__main__":
    create_test_data()
