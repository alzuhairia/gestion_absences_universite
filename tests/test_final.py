import os
import django

# Configuration de l'environnement Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from apps.accounts.models import User

def test_db_connection():
    print("--- Test de connexion PostgreSQL ---")
    try:
        # On essaie de compter les utilisateurs dans ta table 'utilisateur'
        user_count = User.objects.count()
        print(f"✅ Connexion réussie !")
        print(f"📊 Nombre d'utilisateurs trouvés dans la base : {user_count}")
        
        if user_count > 0:
            first_user = User.objects.first()
            print(f"👤 Premier utilisateur trouvé : {first_user.nom} {first_user.prenom} ({first_user.email})")
        else:
            print("ℹ️ La table est connectée mais elle est vide.")
            
    except Exception as e:
        print(f"❌ Erreur lors du test : {e}")

if __name__ == "__main__":
    test_db_connection()