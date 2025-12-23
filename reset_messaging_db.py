import os
import django
import sys
from django.db import connection

# Setup Django environment
sys.path.append(r'C:\Users\ahmed\Desktop\gestion_absences_universite')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

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
