import os
import sys
from pathlib import Path
# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
from django.db import connection

def check_schema_django():
    with connection.cursor() as cursor:
        table_name = 'justification' 
        print(f"Checking columns for table '{table_name}' using Django Connection...")
        # Postgres specific query or generic
        # For postgres: SELECT column_name FROM information_schema.columns WHERE table_name = 'justification';
        
        cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s;", [table_name])
        columns = [row[0] for row in cursor.fetchall()]
        
        print("Columns found:", columns)
        
        if 'commentaire_gestion' in columns:
            print("\nSUCCESS: 'commentaire_gestion' column FOUND.")
        else:
            print("\nFAILURE: 'commentaire_gestion' column NOT FOUND.")

if __name__ == '__main__':
    check_schema_django()
)

if __name__ == '__main__':
    check_schema_django()
