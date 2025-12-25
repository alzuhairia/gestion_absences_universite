import os
import django
import sys
from django.test import RequestFactory

sys.path.append(r'C:\Users\ahmed\Desktop\gestion_absences_universite')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.accounts.models import User
from apps.dashboard.views_export import export_student_pdf, export_at_risk_excel

def verify():
    print("Verifying Export & Reporting...")
    
    # 1. Verify PDF Export
    student = User.objects.filter(role=User.Role.ETUDIANT).first()
    if not student:
        print("No student found. Setup UAT data first.")
    else:
        factory = RequestFactory()
        request = factory.get(f'/dashboard/export/student/pdf/')
        request.user = student
        
        print("Generating Student PDF...")
        try:
            response = export_student_pdf(request)
            if response.status_code == 200 and response['Content-Type'] == 'application/pdf':
                print("PASS: PDF generated successfully (Status 200, application/pdf).")
                # Optional: Write to file to check manualy
                # with open('test_report.pdf', 'wb') as f:
                #     f.write(response.content)
            else:
                print(f"FAIL: PDF generation failed. Status: {response.status_code}")
        except Exception as e:
             print(f"FAIL: PDF generation error: {e}")

    # 2. Verify Excel Export
    secretary = User.objects.filter(role=User.Role.SECRETAIRE).first()
    if not secretary:
        print("No secretary found.")
    else:
        factory = RequestFactory()
        request = factory.get(f'/dashboard/export/secretary/excel/')
        request.user = secretary
        
        print("Generating Excel Export...")
        try:
            response = export_at_risk_excel(request)
            if response.status_code == 200 and 'spreadsheetml' in response['Content-Type']:
                print("PASS: Excel generated successfully.")
            else:
                print(f"FAIL: Excel generation failed. Status: {response.status_code}")
        except Exception as e:
             print(f"FAIL: Excel generation error: {e}")

if __name__ == "__main__":
    verify()
