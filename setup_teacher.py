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

def create_teacher_test_data():
    print("Creating TEACHER test data...")

    # 1. Create Professor
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

    # 2. Assign Course to Professor
    try:
        cours = Cours.objects.get(code_cours="INFO101")
        cours.professeur = prof
        cours.save()
        print(f"Assigned {cours} to {prof}")
    except Cours.DoesNotExist:
        print("Error: INFO101 course not found. Run setup_test_data_v4.py first.")

    # 3. Create another course NOT assigned to this professor (to test visibility)
    faculte, _ = Faculte.objects.get_or_create(nom_faculte="Sciences")
    departement, _ = Departement.objects.get_or_create(nom_departement="Informatique", defaults={'id_faculte': faculte})
    
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
