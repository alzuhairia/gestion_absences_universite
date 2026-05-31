"""
UniAbsences – scripts.setup.setup_test_data_v3
===============================================

Version 3 data-seeding script.  Fixes a model mismatch discovered during
development: the ``Seance`` model does not have a ``type_seance`` field, so
that argument is removed from session creation calls.  The required
``id_annee`` field is added to ``Seance`` instead.

Key differences from V2
-----------------------
* ``AnneeAcademique`` is looked up by ``libelle`` (not ``code_annee``), which
  matches the actual model field name on the deployed schema.
* ``Seance.objects.create`` no longer passes ``type_seance`` (field does not
  exist on the model in this version of the schema).
* ``id_annee`` is explicitly set on every ``Seance`` record.
* Idempotency guard: if a justification is already present via the reverse
  relation, it is not created again.

What this script creates
------------------------
Same logical dataset as V2 (admin, student, INFO101, 2024-2025 year,
enrollment, two absences, one justification) but with corrected field usage.

Usage
-----
::

    python scripts/setup/setup_test_data_v3.py

Part of: UniAbsences setup / test-data seeding layer (v3).
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
from datetime import timedelta


def create_test_data() -> None:
    """Seed the V3 test dataset with corrected model field usage.

    Creates or retrieves all required records.  Absence and justification
    creation is skipped if records already exist; a missing justification is
    added on existing data if needed.
    """
    print("Creating test data with CORRECT Models...")

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

    # V3 fix: use ``libelle`` as the lookup key (the actual model field name).
    annee, _ = AnneeAcademique.objects.get_or_create(
        libelle="2024-2025",
        defaults={'active': True}
    )

    # ------------------------------------------------------------------
    # Step 3 – Enrollment
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
    # V3 fix: ``Seance`` does not have a ``type_seance`` field in this
    # schema version; pass ``id_annee`` instead.
    # ------------------------------------------------------------------
    current_absences = Absence.objects.filter(id_inscription=inscription).count()

    if current_absences == 0:
        base_time = timezone.now()

        # Session 1 – 20 h unjustified absence.
        seance1 = Seance.objects.create(
            id_cours=cours,
            id_annee=annee,  # Required FK – added in V3
            date_seance=base_time.date(),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time()
            # type_seance is intentionally omitted – field does not exist on
            # the Seance model in this schema version.
        )
        Absence.objects.create(
            id_inscription=inscription,
            id_seance=seance1,
            duree_absence=20.0,
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first()
        )

        # Session 2 – 20 h pending absence with immediate justification.
        seance2 = Seance.objects.create(
            id_cours=cours,
            id_annee=annee,
            date_seance=base_time.date() + timedelta(days=1),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time()
        )
        abs_to_justify = Absence.objects.create(
            id_inscription=inscription,
            id_seance=seance2,
            duree_absence=20.0,
            statut='EN_ATTENTE',
            encodee_par=User.objects.first()
        )

        Justification.objects.create(
            id_absence=abs_to_justify,
            document=b"fake_pdf_content",
            commentaire="Created by Setup V3",
            validee=False
        )

        print("Created Absences and Pending Justification.")

    else:
        print("Absences already exist. Adding justification if needed.")
        pending = Absence.objects.filter(
            id_inscription=inscription, statut='EN_ATTENTE'
        ).exists()
        if not pending:
            last_abs = Absence.objects.filter(id_inscription=inscription).last()
            if last_abs:
                last_abs.statut = 'EN_ATTENTE'
                last_abs.save()
                # Guard against creating a duplicate justification via the
                # reverse OneToOne accessor.
                if not hasattr(last_abs, 'justification'):
                    Justification.objects.create(
                        id_absence=last_abs,
                        document=b"fake_pdf_content",
                        commentaire="Added by Setup V3 Update",
                        validee=False
                    )
                print("Added missing justification.")


if __name__ == "__main__":
    create_test_data()
