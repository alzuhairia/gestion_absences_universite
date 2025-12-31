#!/bin/bash
# ============================================
# Script d'entrée pour le conteneur Docker
# ============================================
# IMPORTANT POUR LA SOUTENANCE :
# Ce script s'exécute automatiquement au démarrage du conteneur
# Il garantit que la base de données est prête avant de lancer l'application

set -e  # Arrêter le script en cas d'erreur

echo "🚀 Démarrage du conteneur UniAbsences..."

# ============================================
# ÉTAPE 1 : Attendre que PostgreSQL soit prêt
# ============================================
# IMPORTANT : Django ne peut pas démarrer si PostgreSQL n'est pas disponible
# Ce script attend jusqu'à ce que PostgreSQL accepte les connexions

echo "⏳ Attente de la disponibilité de PostgreSQL..."
until PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -d "postgres" -c '\q' 2>/dev/null; do
    echo "   PostgreSQL n'est pas encore prêt, nouvelle tentative dans 2 secondes..."
    sleep 2
done
echo "✅ PostgreSQL est prêt !"

# ============================================
# ÉTAPE 2 : Créer la base de données si elle n'existe pas
# ============================================
# Cette étape crée automatiquement la base de données si elle n'existe pas
# Utile pour le premier déploiement

echo "📊 Vérification de l'existence de la base de données..."
PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -d "postgres" -tc \
    "SELECT 1 FROM pg_database WHERE datname = '$DB_NAME'" | \
    grep -q 1 || \
    PGPASSWORD=$DB_PASSWORD psql -h "$DB_HOST" -U "$DB_USER" -d "postgres" -c \
    "CREATE DATABASE $DB_NAME"
echo "✅ Base de données '$DB_NAME' prête !"

# ============================================
# ÉTAPE 3 : Exécuter les migrations Django
# ============================================
# IMPORTANT : Les migrations créent/modifient les tables de la base de données
# Elles doivent être exécutées avant de lancer l'application

echo "🔄 Exécution des migrations Django..."
python manage.py migrate --noinput
echo "✅ Migrations terminées !"

# ============================================
# ÉTAPE 4 : Collecter les fichiers statiques
# ============================================
# IMPORTANT : En production, Django ne sert pas les fichiers statiques
# Ils doivent être collectés dans un répertoire et servis par Nginx
# Cette commande copie tous les fichiers statiques (CSS, JS, images) dans /app/staticfiles

echo "📦 Collecte des fichiers statiques..."
python manage.py collectstatic --noinput --clear
echo "✅ Fichiers statiques collectés !"

# ============================================
# ÉTAPE 5 : Créer un superutilisateur si nécessaire (optionnel)
# ============================================
# Cette étape est commentée par défaut
# Décommenter si vous voulez créer automatiquement un superutilisateur au premier démarrage
# ATTENTION : Ne pas utiliser en production avec des mots de passe en dur !

# echo "👤 Création du superutilisateur (si nécessaire)..."
# python manage.py shell << EOF
# from apps.accounts.models import User
# if not User.objects.filter(role=User.Role.ADMIN).exists():
#     User.objects.create_superuser(
#         email='admin@example.com',
#         nom='Admin',
#         prenom='System',
#         password='changeme123'
#     )
#     print("Superutilisateur créé !")
# else:
#     print("Superutilisateur existe déjà.")
# EOF

# ============================================
# ÉTAPE 6 : Lancer Gunicorn
# ============================================
# Gunicorn est le serveur WSGI recommandé pour Django en production
# Il remplace le serveur de développement (runserver) qui n'est pas sécurisé
# Les paramètres sont définis dans le CMD du Dockerfile

echo "🎯 Lancement de Gunicorn..."
echo "   Application disponible sur http://0.0.0.0:8000"
echo "   (Nginx reverse proxy sur le port 80)"

# Exécuter la commande passée en argument (généralement Gunicorn)
exec "$@"
