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

def force_add_column():
    with connection.cursor() as cursor:
        print("Attempting to force add 'state' column to 'justification'...")
        try:
            cursor.execute("ALTER TABLE justification ADD COLUMN state varchar(20) DEFAULT 'EN_ATTENTE';")
            print("SUCCESS: SQL executed.")
        except Exception as e:
            print(f"FAILURE: {e}")

if __name__ == '__main__':
    force_add_column()
e}")

if __name__ == '__main__':
    force_add_column()
