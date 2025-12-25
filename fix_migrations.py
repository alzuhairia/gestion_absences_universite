"""
Script pour corriger l'historique des migrations Django.
Marque academic_sessions.0001_initial comme appliquée avant enrollments.0001_initial.
"""
import os
import django
import sys

# Setup Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.db import connection
from django.utils import timezone
from datetime import datetime, timedelta

def fix_migration_history():
    """Corrige l'historique des migrations"""
    with connection.cursor() as cursor:
        # Vérifier si academic_sessions.0001_initial existe déjà
        cursor.execute("""
            SELECT id FROM django_migrations 
            WHERE app = 'academic_sessions' AND name = '0001_initial'
        """)
        exists = cursor.fetchone()
        
        if exists:
            print("[OK] Migration academic_sessions.0001_initial existe deja")
            return
        
        # Récupérer la date de enrollments.0001_initial
        cursor.execute("""
            SELECT applied FROM django_migrations 
            WHERE app = 'enrollments' AND name = '0001_initial'
        """)
        enrollments_date = cursor.fetchone()
        
        if not enrollments_date:
            print("[WARNING] Migration enrollments.0001_initial non trouvee")
            return
        
        # Insérer academic_sessions.0001_initial avec une date antérieure
        applied_date = enrollments_date[0] - timedelta(seconds=1)
        
        cursor.execute("""
            INSERT INTO django_migrations (app, name, applied)
            VALUES ('academic_sessions', '0001_initial', %s)
        """, [applied_date])
        
        print(f"[OK] Migration academic_sessions.0001_initial ajoutee avec date: {applied_date}")
        print("[OK] Historique des migrations corrige")

if __name__ == '__main__':
    try:
        fix_migration_history()
        print("\n[SUCCESS] Correction terminee. Vous pouvez maintenant executer: python manage.py migrate")
    except Exception as e:
        print(f"\n[ERROR] Erreur: {e}")
        import traceback
        traceback.print_exc()

