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
from django.contrib.messages.storage.fallback import FallbackStorage

from apps.accounts.models import User
from apps.absences.models import Absence, Justification
from apps.notifications.models import Notification
from apps.absences.views_validation import process_justification

def verify():
    print("Verifying Justification Workflow...")
    
    # Setup Data
    student = User.objects.filter(role=User.Role.ETUDIANT).first()
    secretary = User.objects.filter(role=User.Role.SECRETAIRE).first()
    absence = Absence.objects.filter(statut='EN_ATTENTE').first()
    
    if not absence:
        print("No pending absence found. Creating one...")
        # (Assuming enrollment exists from previous setup)
        # For simplicity, just finding ANY absence or skipping if none
        absence = Absence.objects.first()
        if not absence:
            print("No absences at all. Run setup_uat_data first.")
            return

    # Create Justification
    j, created = Justification.objects.get_or_create(id_absence=absence)
    j.state = 'EN_ATTENTE'
    j.save()
    print(f"Test Justification ID: {j.pk} in state {j.state}")

    # Test REJECT
    factory = RequestFactory()
    request = factory.post(f'/absences/process/{j.pk}/', {
        'action': 'reject',
        'comment': 'Test Rejection Reason'
    })
    request.user = secretary
    
    # Middleware for messages
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)

    print("Executing Reject Action...")
    process_justification(request, j.pk)
    
    # Reload and Check
    j.refresh_from_db()
    absence.refresh_from_db()
    
    print(f"New State: {j.state}")
    print(f"Absence Status: {absence.statut}")
    print(f"Comment: {j.commentaire_gestion}")
    
    if j.state == 'REFUSEE' and absence.statut == 'NON_JUSTIFIEE':
        print("PASS: Rejection logic correct.")
    else:
        print("FAIL: Rejection logic failed.")

    # Check Notification
    notif = Notification.objects.filter(id_utilisateur=student).order_by('-date_envoi').first()
    if notif and "REFUSÉE" in notif.message:
        print(f"PASS: Notification sent: {notif.message}")
    else:
        print("FAIL: Notification not found or incorrect.")

if __name__ == "__main__":
    verify()
