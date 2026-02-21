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
def reset_messaging_db():
    print("Resetting Messaging App Database limits...")
    with connection.cursor() as cursor:
        # Drop table if exists
        cursor.execute("DROP TABLE IF EXISTS message;")
        print("Dropped table 'message'.")
        
        # Clear migration history for 'messaging'
        cursor.execute("DELETE FROM django_migrations WHERE app = 'messaging';")
        print("Cleared migration history for 'messaging'.")

if __name__ == "__main__":
    reset_messaging_db()
