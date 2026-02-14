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
from apps.enrollments.models import Inscription
from apps.enrollments.views_rules import toggle_exemption

def verify():
    print("Verifying 40% Rule & Exceptions...")
    
    # Setup Data
    secretary = User.objects.filter(role=User.Role.SECRETAIRE).first()
    # Find an inscription (ideally one that is at risk, but for logic test any works)
    inscription = Inscription.objects.first()
    
    if not inscription:
        print("No inscription found. Setup UAT data first.")
        return

    print(f"Testing on Inscription {inscription.pk} (Student: {inscription.id_etudiant})")

    # Mock Request for Granting Exemption
    factory = RequestFactory()
    request = factory.post(f'/enrollments/rules/toggle/{inscription.pk}/', {
        'action': 'grant',
        'motif': 'Verification Test Exemption'
    })
    request.user = secretary
    
    # Middleware for messages
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)

    print("Granting Exemption...")
    toggle_exemption(request, inscription.pk)
    
    inscription.refresh_from_db()
    if inscription.exemption_40:
        print(f"PASS: Exemption granted. Motif: {inscription.motif_exemption}")
    else:
        print("FAIL: Exemption NOT granted.")

    # Mock Request for Revoking Exemption
    request_revoke = factory.post(f'/enrollments/rules/toggle/{inscription.pk}/', {
        'action': 'revoke'
    })
    request_revoke.user = secretary
    setattr(request_revoke, 'session', 'session')
    setattr(request_revoke, '_messages', FallbackStorage(request_revoke))

    print("Revoking Exemption...")
    toggle_exemption(request_revoke, inscription.pk)
    
    inscription.refresh_from_db()
    if not inscription.exemption_40:
        print("PASS: Exemption revoked.")
    else:
        print("FAIL: Exemption NOT revoked.")

if __name__ == "__main__":
    verify()
