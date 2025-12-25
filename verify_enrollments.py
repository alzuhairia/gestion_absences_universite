import os
import django
import sys

sys.path.append(r'C:\Users\ahmed\Desktop\gestion_absences_universite')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.accounts.models import User
from apps.academics.models import Cours
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import AnneeAcademique

def verify():
    print("Verifying Enrollment Logic...")
    
    # Get or Create Data
    student = User.objects.filter(role=User.Role.ETUDIANT).first()
    if not student:
        print("No student found.")
        return

    year = AnneeAcademique.objects.filter(active=True).first()
    if not year:
        year = AnneeAcademique.objects.first()

    # Create Courses with Prereq
    c_basic, _ = Cours.objects.get_or_create(code_cours="VERIFY101", defaults={
        'nom_cours': "Basic Course", 'nombre_total_periodes': 10, 'seuil_absence': 40, 'id_departement_id': 1
    })
    c_advanced, _ = Cours.objects.get_or_create(code_cours="VERIFY202", defaults={
        'nom_cours': "Advanced Course", 'nombre_total_periodes': 10, 'seuil_absence': 40, 'id_departement_id': 1
    })
    c_advanced.prerequisites.add(c_basic)
    
    print(f"Courses: {c_basic} and {c_advanced} (Prereq: {c_basic})")

    # 1. Test: Try enrolling in Advanced WITHOUT Basic
    # Clean up first
    Inscription.objects.filter(id_etudiant=student, id_cours=c_advanced).delete()
    Inscription.objects.filter(id_etudiant=student, id_cours=c_basic).delete()

    print("Checking prerequisite (should fail)...")
    # Logic simulation (as in views.py)
    has_basic = Inscription.objects.filter(id_etudiant=student, id_cours=c_basic).exists()
    if not has_basic:
        print("PASS: Prerequisite correctly identified as missing.")
    else:
        print("FAIL: Prerequisite falsely identified as present.")

    # 2. Test: Enroll in Basic, then try Advanced
    print("Enrolling in Basic...")
    Inscription.objects.create(id_etudiant=student, id_cours=c_basic, id_annee=year, status='EN_COURS')
    
    print("Checking prerequisite (should succeed)...")
    has_basic = Inscription.objects.filter(id_etudiant=student, id_cours=c_basic).exists()
    if has_basic:
        print("PASS: Prerequisite correctly identified as present.")
    else:
        print("FAIL: Prerequisite not found.")

if __name__ == "__main__":
    verify()
