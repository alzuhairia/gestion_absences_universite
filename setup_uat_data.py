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
from apps.absences.models import Absence
from apps.notifications.models import Notification
from django.utils import timezone
from datetime import timedelta

def create_uat_data():
    print("Creating UAT data...")

    # 1. User
    email = "uat.student@uni.edu"
    if not User.objects.filter(email=email).exists():
        student = User.objects.create_user(
            email=email,
            nom="Test",
            prenom="UAT",
            password="uatpassword",
            role=User.Role.ETUDIANT
        )
    else:
        student = User.objects.get(email=email)

    # 2. Year & Dept
    annee, _ = AnneeAcademique.objects.get_or_create(libelle="2024-2025", defaults={'active': True})
    faculte, _ = Faculte.objects.get_or_create(nom_faculte="UAT Fac")
    dept, _ = Departement.objects.get_or_create(nom_departement="UAT Dept", defaults={'id_faculte': faculte})

    # 3. Courses
    courses_config = [
        {"code": "GREEN101", "name": "Course Green (20%)", "abs": 20},
        {"code": "ORANGE101", "name": "Course Orange (35%)", "abs": 35},
        {"code": "RED101", "name": "Course Red (45%)", "abs": 45},
    ]

    base_time = timezone.now()

    for conf in courses_config:
        cours, _ = Cours.objects.get_or_create(
            code_cours=conf["code"],
            defaults={
                'nom_cours': conf["name"],
                'nombre_total_periodes': 100, # 100h
                'seuil_absence': 40, # 40%
                'id_departement': dept
            }
        )
        
        # Enrollment
        insc, _ = Inscription.objects.get_or_create(
            id_etudiant=student, id_cours=cours, id_annee=annee,
            defaults={'eligible_examen': True}
        )

        # Clear existing absences for this inscription to ensure clean state
        Absence.objects.filter(id_inscription=insc).delete()

        # Create Absence
        seance = Seance.objects.create(
            id_cours=cours, id_annee=annee,
            date_seance=base_time.date(),
            heure_debut=base_time.time(),
            heure_fin=(base_time + timedelta(hours=4)).time()
        )
        
        Absence.objects.create(
            id_inscription=insc,
            id_seance=seance,
            duree_absence=float(conf["abs"]),
            statut='NON_JUSTIFIEE',
            encodee_par=User.objects.first() or student
        )
        print(f"Created {conf['code']} with {conf['abs']}h absence.")

    # 4. Notifications
    Notification.objects.filter(id_utilisateur=student).delete()
    for i in range(1, 6):
        Notification.objects.create(
            id_utilisateur=student,
            message=f"UAT Notification Test #{i}",
            date_envoi=timezone.now() - timedelta(minutes=i*10),
            lue=False
        )
    print("Created 5 notifications.")

if __name__ == "__main__":
    create_uat_data()
