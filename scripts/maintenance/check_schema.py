import os
import sys
from pathlib import Path
# Ajouter le répertoire racine au PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()
import sqlite3

def check_schema():
    db_path = 'db.sqlite3'
    if not os.path.exists(db_path):
        print("db.sqlite3 not found!")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    table_name = 'justification' # From Meta: db_table = 'justification'
    
    print(f"Checking columns for table '{table_name}'...")
    try:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = cursor.fetchall()
        
        found = False
        for col in columns:
            print(col)
            if col[1] == 'commentaire_gestion':
                found = True
        
        if found:
            print("\nSUCCESS: 'commentaire_gestion' column FOUND.")
        else:
            print("\nFAILURE: 'commentaire_gestion' column NOT FOUND.")
            
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    check_schema()
.close()

if __name__ == '__main__':
    check_schema()
