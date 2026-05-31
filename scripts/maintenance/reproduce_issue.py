"""
UniAbsences – scripts.maintenance.reproduce_issue
=================================================

Minimal reproduction harness for a reported bug in the PDF report generation
view (``accounts.views.download_report_pdf``).

How it works
------------
The script retrieves the UAT student account (``uat.student@uni.edu``),
constructs a bare ``HttpRequest`` object with that user set, calls the view
function directly (bypassing URL routing), and prints the response metadata.
If an unhandled exception is raised the full traceback is written to
``traceback.txt`` in the working directory for offline inspection.

Usage
-----
Run from the project root when the bug needs to be reproduced locally::

    python scripts/maintenance/reproduce_issue.py

After reproduction, ``traceback.txt`` (if created) contains the captured
exception and stack trace.

Part of: UniAbsences maintenance / debugging layer.
"""

import os
import sys
from pathlib import Path

# Bootstrap Django before importing any application modules.
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
    # Locate the UAT student used for manual testing.
    user = User.objects.get(email='uat.student@uni.edu')
    print(f"User found: {user}")

    # Build the minimum request object the view requires.
    # Middleware-provided attributes (e.g. session, messages) are not set
    # here because this is a raw function call, not a full request cycle.
    request = HttpRequest()
    request.user = user

    # Invoke the view directly to exercise the PDF generation path.
    print("Calling download_report_pdf...")
    response = download_report_pdf(request)

    print(f"Response status: {response.status_code}")
    print(f"Content type: {response['Content-Type']}")
    print("PDF generation successful (mock).")

except Exception as e:
    import traceback
    # Write the full traceback to a file so it can be reviewed without
    # the terminal session being open.
    with open('traceback.txt', 'w') as f:
        f.write(f"CRITICAL ERROR CAUGHT:\n{e}\n")
        traceback.print_exc(file=f)
    print("Error occurred, check traceback.txt")
