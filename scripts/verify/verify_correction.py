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
from apps.audits.models import LogAudit
from apps.absences.views_manager import edit_absence

def verify():
    print("Verifying Absence Correction & Audit...")
    
    # Setup Data
    secretary = User.objects.filter(role=User.Role.SECRETAIRE).first()
    absence = Absence.objects.first() # Grab any absence
    
    if not absence:
        print("No absence found. Setup UAT data first.")
        return

    print(f"Testing on Absence {absence.pk} (Status: {absence.statut})")

    # Mock Request for Edit
    factory = RequestFactory()
    request = factory.post(f'/absences/edit/{absence.pk}/', {
        'duree_absence': absence.duree_absence, # Keep same
        'type_absence': absence.type_absence,   # Keep same
        'statut': 'JUSTIFIEE',                  # CHANGE STATUS (Override)
        'reason': 'Audit Verification Test'
    })
    request.user = secretary
    
    # Middleware for messages
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)

    print("Executing Edit (Override)...")
    edit_absence(request, absence.pk)
    
    # Verify Absence Updatre
    absence.refresh_from_db()
    if absence.statut == 'JUSTIFIEE':
        print("PASS: Absence status updated to JUSTIFIEE.")
    else:
        print(f"FAIL: Absence status is {absence.statut}")

    # Verify Audit Log
    log = LogAudit.objects.filter(id_utilisateur=secretary).order_by('-date_action').first()
    if log and "UPDATED" in log.action and "Audit Verification Test" in log.action:
        print(f"PASS: Audit Log found: {log.action}")
    else:
        print("FAIL: Audit Log missing or incorrect.")

if __name__ == "__main__":
    verify()
r incorrect.")

if __name__ == "__main__":
    verify()
