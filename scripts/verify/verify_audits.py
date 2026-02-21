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
from apps.audits.views import audit_list
from apps.audits.models import LogAudit
from apps.audits.utils import log_action

def verify():
    print("Verifying Audit & Traceability...")
    
    # Setup Data
    secretary = User.objects.filter(role=User.Role.SECRETAIRE).first()
    
    # 1. Create a fresh log
    print("Creating a test audit log...")
    log_action(secretary, "VERIFICATION: Test Audit Log Entry")
    
    # 2. Test Audit List View
    factory = RequestFactory()
    request = factory.get('/audits/logs/')
    request.user = secretary
    
    print("Accessing Audit List View...")
    response = audit_list(request)
    
    if response.status_code == 200:
        print("PASS: Audit View accessible (Status 200).")
        
        # Verify content contains the log we just made
        content = response.content.decode('utf-8')
        if "VERIFICATION: Test Audit Log Entry" in content:
            print("PASS: New log entry found in view.")
        else:
            print("FAIL: Log entry NOT found in view.")
    else:
        print(f"FAIL: Audit View failed. Status: {response.status_code}")

    # 3. Test Search
    request_search = factory.get('/audits/logs/?q=VERIFICATION')
    request_search.user = secretary
    
    print("Testing Search...")
    response_search = audit_list(request_search)
    content_search = response_search.content.decode('utf-8')
    if "VERIFICATION: Test Audit Log Entry" in content_search:
        print("PASS: Search returned correct result.")
    else:
        print("FAIL: Search failed.")

if __name__ == "__main__":
    verify()
