# 🐳 Configuration Docker - UniAbsences

## 📋 Fichiers créés pour le déploiement Docker

Ce document liste tous les fichiers créés pour le déploiement Docker en production.

---

## ✅ Fichiers créés

### 1. **Dockerfile**
- **Emplacement** : `/Dockerfile`
- **Rôle** : Image Docker pour l'application Django
- **Fonctionnalités** :
  - Build multi-stage pour optimiser la taille
  - Installation des dépendances Python
  - Utilisateur non-root pour la sécurité
  - Configuration Gunicorn pour la production

### 2. **docker-compose.yml**
- **Emplacement** : `/docker-compose.yml`
- **Rôle** : Orchestration des services Docker
- **Services** :
  - `web` : Application Django (Gunicorn)
  - `db` : Base de données PostgreSQL
  - `nginx` : Reverse proxy et serveur web
- **Volumes** : Persistance des données (DB, static, media, logs)

### 3. **entrypoint.sh**
- **Emplacement** : `/entrypoint.sh`
- **Rôle** : Script d'initialisation du conteneur
- **Fonctionnalités** :
  - Attente de PostgreSQL
  - Création automatique de la base de données
  - Exécution des migrations
  - Collecte des fichiers statiques
  - Lancement de Gunicorn

### 4. **nginx/Dockerfile**
- **Emplacement** : `/nginx/Dockerfile`
- **Rôle** : Image Docker pour Nginx
- **Fonctionnalités** : Configuration Nginx personnalisée

### 5. **nginx/nginx.conf**
- **Emplacement** : `/nginx/nginx.conf`
- **Rôle** : Configuration Nginx
- **Fonctionnalités** :
  - Reverse proxy vers Gunicorn
  - Service des fichiers statiques
  - Service des fichiers média
  - Compression Gzip
  - Configuration HTTPS (commentée, prête à activer)

### 6. **.env.example**
- **Emplacement** : `/.env.example`
- **Rôle** : Modèle de configuration
- **Contenu** :
  - Variables Django (SECRET_KEY, DEBUG, ALLOWED_HOSTS)
  - Variables PostgreSQL (DB_NAME, DB_USER, DB_PASSWORD, etc.)
  - Commentaires explicatifs pour chaque variable

### 7. **requirements.txt**
- **Emplacement** : `/requirements.txt`
- **Rôle** : Dépendances Python
- **Contenu** : Toutes les dépendances nécessaires, incluant Gunicorn

### 8. **.dockerignore**
- **Emplacement** : `/.dockerignore`
- **Rôle** : Exclure les fichiers inutiles du build Docker
- **Optimisation** : Réduit la taille de l'image et accélère les builds

### 9. **README_DEPLOYMENT.md**
- **Emplacement** : `/README_DEPLOYMENT.md`
- **Rôle** : Guide complet de déploiement
- **Contenu** :
  - Installation sur VPS
  - Configuration initiale
  - Commandes de gestion
  - Dépannage
  - Configuration HTTPS
  - Sauvegarde et restauration

---

## 🔧 Modifications apportées aux fichiers existants

### 1. **config/settings.py**
- **Modifications** :
  - Configuration de la base de données via variables d'environnement
  - Ajout de `STATIC_ROOT` et `MEDIA_ROOT` pour Docker
  - Amélioration de la gestion de `DEBUG` avec valeur par défaut

### 2. **.gitignore**
- **Modifications** :
  - Ajout de `.env.production` et `.env.local`
  - Ajout de `.dockerignore`

---

## 🚀 Commandes de déploiement

### Première installation

```bash
# 1. Créer le fichier .env
cp .env.example .env
nano .env  # Configurer les variables

# 2. Construire et démarrer
docker compose up -d --build

# 3. Créer un superutilisateur
docker compose exec web python manage.py createsuperuser
```

### Gestion quotidienne

```bash
# Voir les logs
docker compose logs -f

# Redémarrer
docker compose restart

# Arrêter
docker compose stop

# Mettre à jour
git pull
docker compose up -d --build
docker compose exec web python manage.py migrate
```

---

## 📌 Points importants pour la soutenance

### Architecture Docker

1. **3 services isolés** :
   - `web` : Application Django (Gunicorn)
   - `db` : Base de données PostgreSQL
   - `nginx` : Reverse proxy et serveur web

2. **Volumes persistants** :
   - `postgres_data` : Base de données
   - `static_volume` : Fichiers statiques
   - `media_volume` : Fichiers uploadés
   - `logs_volume` : Logs de l'application

3. **Réseau Docker** :
   - Communication isolée entre les services
   - Sécurité renforcée

### Sécurité

1. **Variables d'environnement** : Tous les secrets dans `.env`
2. **Utilisateur non-root** : Conteneurs exécutés avec un utilisateur limité
3. **Configuration HTTPS** : Prête à activer avec certificats SSL

### Performance

1. **Nginx** : Sert directement les fichiers statiques (plus rapide)
2. **Gunicorn** : 3 workers pour gérer les requêtes
3. **Compression Gzip** : Réduction de la taille des réponses

---

## ✅ Checklist de déploiement

- [ ] Fichier `.env` créé et configuré
- [ ] `SECRET_KEY` générée et unique
- [ ] `DEBUG=False` en production
- [ ] `ALLOWED_HOSTS` configuré avec votre domaine/IP
- [ ] Mot de passe PostgreSQL fort
- [ ] Docker et Docker Compose installés
- [ ] Conteneurs démarrés : `docker compose up -d --build`
- [ ] Superutilisateur créé
- [ ] Application accessible via HTTP/HTTPS
- [ ] Sauvegardes automatiques configurées (optionnel)
- [ ] HTTPS configuré (optionnel mais recommandé)

---

## 🆘 Support

En cas de problème :
1. Consulter `README_DEPLOYMENT.md` (section Dépannage)
2. Vérifier les logs : `docker compose logs`
3. Vérifier le statut : `docker compose ps`

---

**✅ Configuration Docker complète et prête pour la production !**
