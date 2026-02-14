import os
import sys
from pathlib import Path
# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.conf import settings
from apps.accounts.models import User
from django.http import HttpRequest
from apps.accounts.views import download_report_pdf

try:
    # Get the user mentioned in the issue
    user = User.objects.get(email='uat.student@uni.edu')
    print(f"User found: {user}")

    # Create a mock request
    request = HttpRequest()
    request.user = user

    # Call the view
    print("Calling download_report_pdf...")
    response = download_report_pdf(request)
    
    print(f"Response status: {response.status_code}")
    print(f"Content type: {response['Content-Type']}")
    print("PDF generation successful (mock).")

except Exception as e:
    import traceback
    with open('traceback.txt', 'w') as f:
        f.write(f"CRITICAL ERROR CAUGHT:\n{e}\n")
        traceback.print_exc(file=f)
    print("Error occurred, check traceback.txt")
