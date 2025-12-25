import os
import django
from django.test import RequestFactory
from django.contrib.sessions.middleware import SessionMiddleware
from django.contrib.messages.middleware import MessageMiddleware
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User
from apps.absences.models import Absence, Justification
from apps.academics.models import Cours
from apps.academic_sessions.models import Seance
from apps.enrollments.models import Inscription
from apps.absences.views import valider_justificatif, review_justification
from django.urls import reverse

def verify_roles():
    print("--- Verifying Role Separation for Justifications ---")
    
    # 1. Setup Data
    prof = User.objects.filter(role='PROFESSEUR').first()
    if not prof:
        print("Error: No professor found.")
        return

    secretary, _ = User.objects.get_or_create(
        email="secretary@test.com", 
        defaults={'role': 'SECRETAIRE', 'nom': 'Sec', 'prenom': 'Retary'}
    )
    
    student = User.objects.filter(role='ETUDIANT').first()
    course = Cours.objects.filter(professeur=prof).first()
    
    # Create Absence & Justification
    seance, _ = Seance.objects.get_or_create(
        id_cours=course, 
        date_seance=timezone.now().date(), 
        defaults={'heure_debut': '08:00', 'heure_fin': '10:00', 'id_annee_id': 1}
    )
    
    inscription = Inscription.objects.filter(id_etudiant=student, id_cours=course).first()
    if not inscription:
         inscription = Inscription.objects.create(id_etudiant=student, id_cours=course, id_annee_id=1)

    absence, _ = Absence.objects.get_or_create(
        id_inscription=inscription, 
        id_seance=seance,
        defaults={'type_absence': 'SEANCE', 'duree_absence': 2, 'statut': 'EN_ATTENTE', 'encodee_par': prof}
    )
    
    justification, _ = Justification.objects.get_or_create(
        id_absence=absence,
        defaults={'commentaire': 'Sick leave', 'validee': False}
    )
    
    factory = RequestFactory()
    
    # --- TEST 1: PROFESSOR CANNOT VALIDATE ---
    print("\n[Test 1] Professor accessing 'valider_justification'...")
    try:
        url_validate = reverse('absences:valider_justification', args=[absence.id_absence])
        print(f"DEBUG: url_validate = {url_validate}")
    except Exception as e:
        print(f"ERROR reversing valider_justification: {e}")
        return

    request = factory.get(url_validate)
    request.user = prof
    
    # Setup middleware for messages
    SessionMiddleware(lambda x: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda x: None).process_request(request)
    
    response = valider_justificatif(request, absence.id_absence)
    
    if response.status_code == 302 and response.url == reverse('dashboard:index'):
        print("SUCCESS: Professor was redirected (Access Denied).")
    else:
        print(f"FAILURE: Professor got status {response.status_code}, url {getattr(response, 'url', 'N/A')}")

    # --- TEST 2: PROFESSOR CAN REVIEW & COMMENT ---
    print("\n[Test 2] Professor accessing 'review_justification'...")
    try:
        url_review = reverse('absences:review_justification', args=[absence.id_absence])
        print(f"DEBUG: url_review = {url_review}")
    except Exception as e:
         print(f"ERROR reversing review_justification: {e}")
         return
    
    # 2a. Post Comment
    data = {'commentaire_gestion': 'Internal Note by Prof'}
    request = factory.post(url_review, data)
    request.user = prof
    SessionMiddleware(lambda x: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda x: None).process_request(request)
    
    review_justification(request, absence.id_absence)
    
    justification.refresh_from_db()
    if justification.commentaire_gestion == 'Internal Note by Prof':
        print("SUCCESS: Professor added internal comment.")
    else:
        print(f"FAILURE: Comment not saved. Got: {justification.commentaire_gestion}")

    # --- TEST 3: SECRETARY CAN VALIDATE ---
    print("\n[Test 3] Secretary validating justification...")
    request = factory.get(url_validate)
    request.user = secretary
    SessionMiddleware(lambda x: None).process_request(request)
    request.session.save()
    MessageMiddleware(lambda x: None).process_request(request)
    
    valider_justificatif(request, absence.id_absence)
    
    justification.refresh_from_db()
    absence.refresh_from_db()
    
    if justification.validee and absence.statut == 'JUSTIFIEE' and justification.validee_par == secretary:
        print("SUCCESS: Secretary successfully validated the justification.")
    else:
        print(f"FAILURE: Validation failed. Justif Validated: {justification.validee}, Absence Statut: {absence.statut}")

if __name__ == '__main__':
    try:
        verify_roles()
    except Exception as e:
        import traceback
        traceback.print_exc()
