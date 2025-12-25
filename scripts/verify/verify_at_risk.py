import os
import sys
from pathlib import Path
# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.db.models import Sum

from apps.accounts.models import User
from apps.academics.models import Cours, Departement
from apps.absences.models import Absence
from apps.enrollments.models import Inscription
from apps.academic_sessions.models import Seance
from apps.dashboard.views import instructor_dashboard
from django.utils import timezone

def verify_at_risk():
    print("--- Verifying At-Risk Student Detection ---")
    
    # 1. Setup Data
    prof, _ = User.objects.get_or_create(email="risk_prof@univ.edu", defaults={'role': 'PROFESSEUR', 'nom': 'Risk', 'prenom': 'Prof'})
    student, _ = User.objects.get_or_create(email="risk_student@univ.edu", defaults={'role': 'ETUDIANT', 'nom': 'Risk', 'prenom': 'Student'})
    
    dept = Departement.objects.first() or Departement.objects.create(code_dept="RISK", nom_dept="Risk Dept")
    
    # Create Course with known hours (e.g. 10 hours total)
    course, _ = Cours.objects.get_or_create(
        code_cours="RISK101", 
        defaults={
            'nom_cours': 'Risk Management', 
            'professeur': prof, 
            'id_departement': dept,
            'nombre_total_periodes': 10, # 10 Hours Total
            'seuil_absence': 40 # 40% (Default)
        }
    )
    # Ensure total periods is 10 for math simplicity
    course.nombre_total_periodes = 10
    course.professeur = prof
    course.save()
    
    inscription, _ = Inscription.objects.get_or_create(id_etudiant=student, id_cours=course, defaults={'id_annee_id': 1})
    
    # 2. Add Absences to exceed 40%
    # 40% of 10h = 4h
    # Let's add 5 hours of UNJUSTIFIED absence
    
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
            'duree_absence': 5.0, # 5h > 4h
            'type_absence': 'SEANCE',
            'encodee_par': prof
        }
    )
    
    print(f"Set up Student {student} with 5h absence in 10h course (50%). Should be AT RISK.")

    # Debug DB State
    print("\n--- DB DIAGNOSTICS ---")
    absences = Absence.objects.filter(id_inscription=inscription)
    print(f"Total Absences found: {absences.count()}")
    for a in absences:
        print(f" - ID: {a.id_absence}, Durée: {a.duree_absence}, Statut: {a.statut}, Session ID: {a.id_seance.id_seance}")
    
    total_unjustified = Absence.objects.filter(
                id_inscription=inscription, 
                statut='NON_JUSTIFIEE'
            ).aggregate(total=Sum('duree_absence'))['total'] or 0
    print(f"Total Unjustified Calculated: {total_unjustified}h")
    print("----------------------\n")

    # 3. Check Dashboard Response
    factory = RequestFactory()
    request = factory.get('/dashboard/instructor/')
    request.user = prof
    SessionMiddleware(lambda x: None).process_request(request)
    
    # We need to render the view to trigger the logic.
    # Note: instructor_dashboard returns a HttpResponse. 
    # To check context data accurately without parsing HTML, normally we'd use Client().
    # But here we inserted logic into the view. Let's inspect the HTML for the student's name in the Risk Section.
    
    response = instructor_dashboard(request)
    print(f"Response Status Code: {response.status_code}")
    if response.status_code == 302:
        print(f"Redirected to: {response.url}")
        
    content = response.content.decode('utf-8')
    
    # Look for the specific HTML marker we added
    marker = "Attention : Étudiants en situation d'échec"
    student_name = student.get_full_name()
    
    if marker in content:
        print("SUCCESS: 'At Risk' alert section is present.")
        if student_name in content:
            print(f"SUCCESS: Student {student_name} found in the At Risk list.")
        else:
            print(f"FAILURE: Student {student_name} NOT found in HTML (but section exists).")
    else:
        print("FAILURE: 'At Risk' alert section NOT found in HTML.")

if __name__ == '__main__':
    verify_at_risk()
TML.")

if __name__ == '__main__':
    verify_at_risk()
