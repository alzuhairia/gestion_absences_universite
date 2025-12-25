import os
import django
from django.test import Client

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User
from apps.academics.models import Cours, Departement
from apps.absences.models import Absence
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import Seance
from django.utils import timezone
from django.db.models import Sum

def verify_at_risk_client():
    print("--- Verifying At-Risk (Using Client) ---")
    
    # 1. Setup Data
    prof, _ = User.objects.get_or_create(email="risk_prof_c@univ.edu", defaults={'role': 'PROFESSEUR', 'nom': 'RiskC', 'prenom': 'Prof'})
    prof.set_password('testpass')
    prof.save()
    
    student, _ = User.objects.get_or_create(email="risk_stud_c@univ.edu", defaults={'role': 'ETUDIANT', 'nom': 'RiskC', 'prenom': 'Student'})
    
    dept = Departement.objects.first() or Departement.objects.create(code_dept="RISKC", nom_dept="Risk Dept C")
    
    course, _ = Cours.objects.get_or_create(
        code_cours="RISKC101", 
        defaults={
            'nom_cours': 'Risk Management C', 
            'professeur': prof, 
            'id_departement': dept,
            'nombre_total_periodes': 10,
            'seuil_absence': 40
        }
    )
    course.nombre_total_periodes = 10
    course.professeur = prof
    course.save()
    
    inscription, _ = Inscription.objects.get_or_create(id_etudiant=student, id_cours=course, defaults={'id_annee_id': 1})
    
    seance, _ = Seance.objects.get_or_create(
        id_cours=course, 
        date_seance=timezone.now().date(), 
        defaults={'heure_debut': '08:00', 'heure_fin': '13:00', 'id_annee_id': 1}
    )
    
    Absence.objects.update_or_create(
        id_inscription=inscription, 
        id_seance=seance,
        defaults={
            'statut': 'NON_JUSTIFIEE', 
            'duree_absence': 5.0, 
            'type_absence': 'SEANCE',
            'encodee_par': prof
        }
    )
    
    print(f"Data Setup Complete. Prof: {prof.email}, Course: {course.nom_cours}")
    
    # 2. Use Client
    client = Client()
    client.force_login(prof)
    
    response = client.get('/dashboard/')
    
    print(f"Response Status: {response.status_code}")
    
    if response.status_code != 200:
        print(f"Failed to load dashboard. URL: {response.url if hasattr(response, 'url') else 'N/A'}")
        return

    content = response.content.decode('utf-8')
    
    # Check for marker (unique part of the alert section)
    marker = "border-left-danger"
    student_name = student.get_full_name()
    
    if marker in content:
        print("SUCCESS: Alert section found.")
        if student_name in content:
            print(f"SUCCESS: Student {student_name} found in the risk list.")
        else:
            print(f"FAILURE: Student name not found in the list.")
    else:
        print("FAILURE: Alert section NOT found.")
        print("Content Dump (first 500 chars):")
        print(content[:500])

if __name__ == '__main__':
    verify_at_risk_client()
