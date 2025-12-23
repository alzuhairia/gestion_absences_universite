import os
import django
import sys
from datetime import date

# Setup Django environment
sys.path.append(r'C:\Users\ahmed\Desktop\gestion_absences_universite')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.accounts.models import User
from apps.academics.models import Faculte, Departement, Cours
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import Seance, AnneeAcademique
from apps.absences.models import Absence, Justification
from django.utils import timezone
from datetime import timedelta

def create_test_data():
    print("Creating test data with CORRECT Models V4...")

    # 1. Users
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

    # 2. Academics
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
    
    # 3. Annee
    annee, _ = AnneeAcademique.objects.get_or_create(
        libelle="2024-2025",
        defaults={
            'active': True
        }
    )

    # 4. Enrollment
    inscription, created = Inscription.objects.get_or_create(
        id_etudiant=student,
        id_cours=cours,
        id_annee=annee,
        defaults={'eligible_examen': True}
    )
    print(f"Enrollment {'created' if created else 'exists'}: {inscription}")

    # 5. Sessions & Absences
    current_absences = Absence.objects.filter(id_inscription=inscription).count()
    
    if current_absences == 0:
        base_time = timezone.now()
        
        # Seance 1: 4h
        seance1 = Seance.objects.create(
            id_cours=cours,
            id_annee=annee,
            date_seance=base_time.date(),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time()
        )
        Absence.objects.create(
            id_inscription=inscription,
            id_seance=seance1,
            duree_absence=20.0,
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first()
        )
        
        # Seance 2
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
            commentaire="Created by Setup V4",
            validee=False
        )
        
        print("Created Absences and Pending Justification.")

    else:
        print("Absences already exist.")
        pending = Absence.objects.filter(id_inscription=inscription, statut='EN_ATTENTE').exists()
        if not pending:
            last_abs = Absence.objects.filter(id_inscription=inscription).last()
            if last_abs:
                last_abs.statut = 'EN_ATTENTE'
                last_abs.save()
                if not hasattr(last_abs, 'justification'):
                    Justification.objects.create(
                        id_absence=last_abs,
                        document=b"fake_pdf_content",
                        commentaire="Added by Setup V4 Update",
                        validee=False
                    )
                print("Added missing justification.")


if __name__ == "__main__":
    create_test_data()
