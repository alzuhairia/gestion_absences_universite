# 🚀 Guide de Déploiement Docker - UniAbsences

## 📋 Table des matières

1. [Prérequis](#prérequis)
2. [Installation sur un VPS](#installation-sur-un-vps)
3. [Configuration initiale](#configuration-initiale)
4. [Déploiement](#déploiement)
5. [Gestion de l'application](#gestion-de-lapplication)
6. [Mise à jour](#mise-à-jour)
7. [Dépannage](#dépannage)
8. [Configuration HTTPS (optionnel)](#configuration-https-optionnel)
9. [Sauvegarde et restauration](#sauvegarde-et-restauration)

---

## 📌 IMPORTANT POUR LA SOUTENANCE

Ce guide explique comment déployer UniAbsences en production avec Docker. L'architecture comprend :
- **Application Django** (Gunicorn) : Gère la logique métier
- **PostgreSQL** : Base de données
- **Nginx** : Reverse proxy et serveur de fichiers statiques

---

## 1. Prérequis

### Sur votre VPS (Serveur)

- **Système d'exploitation** : Ubuntu 20.04+ ou Debian 11+ (recommandé)
- **RAM** : Minimum 2 GB (4 GB recommandé)
- **Espace disque** : Minimum 10 GB
- **Accès root ou sudo** : Pour installer Docker

### Logiciels requis

- **Docker** : Version 20.10+
- **Docker Compose** : Version 2.0+
- **Git** : Pour cloner le projet

---

## 2. Installation sur un VPS

### Étape 1 : Connexion au serveur

```bash
ssh root@votre-serveur-ip
```

### Étape 2 : Mise à jour du système

```bash
apt update && apt upgrade -y
```

### Étape 3 : Installation de Docker

```bash
# Installer les dépendances
apt install -y apt-transport-https ca-certificates curl gnupg lsb-release

# Ajouter la clé GPG officielle de Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Ajouter le dépôt Docker
echo "deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

# Installer Docker
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Vérifier l'installation
docker --version
docker compose version
```

### Étape 4 : Installation de Git

```bash
apt install -y git
```

---

## 3. Configuration initiale

### Étape 1 : Cloner le projet

```bash
# Créer un répertoire pour l'application
mkdir -p /opt/unabsences
cd /opt/unabsences

# Cloner le projet (remplacer par votre URL Git)
git clone https://github.com/votre-username/unabsences.git .

# OU si vous avez déjà le code, copiez-le sur le serveur
```

### Étape 2 : Créer le fichier .env

```bash
# Copier le fichier d'exemple
cp .env.example .env

# Éditer le fichier .env
nano .env
```

**Variables à configurer dans .env :**

```env
# Générer une SECRET_KEY unique
SECRET_KEY=votre-cle-secrete-generee-avec-django

# Mode production
DEBUG=False

# Votre domaine ou IP
ALLOWED_HOSTS=votre-domaine.com,www.votre-domaine.com,123.456.789.0

# Base de données
DB_NAME=unabsences_db
DB_USER=postgres
DB_PASSWORD=votre-mot-de-passe-fort-et-securise
DB_HOST=db
DB_PORT=5432
```

**📌 IMPORTANT : Générer la SECRET_KEY**

```bash
# Depuis votre machine locale ou le serveur
python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copiez la clé générée dans `SECRET_KEY=` de votre fichier `.env`.

### Étape 3 : Vérifier les permissions

```bash
# Rendre le script d'entrée exécutable
chmod +x entrypoint.sh
```

---

## 4. Déploiement

### Étape 1 : Construire et démarrer les conteneurs

```bash
# Construire les images Docker et démarrer les services
docker compose up -d --build
```

**Explication de la commande :**
- `up` : Démarrer les conteneurs
- `-d` : Mode détaché (en arrière-plan)
- `--build` : Reconstruire les images si nécessaire

### Étape 2 : Vérifier le statut

```bash
# Voir les conteneurs en cours d'exécution
docker compose ps

# Voir les logs
docker compose logs -f
```

Vous devriez voir 3 conteneurs :
- `unabsences_web` : Application Django
- `unabsences_db` : Base de données PostgreSQL
- `unabsences_nginx` : Serveur web Nginx

### Étape 3 : Créer un superutilisateur

```bash
# Accéder au conteneur Django
docker compose exec web python manage.py createsuperuser

# Suivre les instructions pour créer un compte admin
```

### Étape 4 : Accéder à l'application

Ouvrez votre navigateur et accédez à :
- **HTTP** : `http://votre-domaine.com` ou `http://votre-ip`
- **Interface Admin** : `http://votre-domaine.com/admin/`

---

## 5. Gestion de l'application

### Voir les logs

```bash
# Logs de tous les services
docker compose logs -f

# Logs d'un service spécifique
docker compose logs -f web
docker compose logs -f nginx
docker compose logs -f db
```

### Arrêter l'application

```bash
# Arrêter les conteneurs (sans supprimer les données)
docker compose stop
```

### Redémarrer l'application

```bash
# Redémarrer les conteneurs
docker compose restart

# OU redémarrer un service spécifique
docker compose restart web
```

### Arrêter et supprimer les conteneurs

```bash
# ATTENTION : Cela supprime les conteneurs mais PAS les volumes (données conservées)
docker compose down

# Supprimer aussi les volumes (⚠️ SUPPRIME LES DONNÉES)
docker compose down -v
```

### Accéder au shell du conteneur

```bash
# Shell du conteneur Django
docker compose exec web bash

# Shell PostgreSQL
docker compose exec db psql -U postgres -d unabsences_db
```

### Exécuter des commandes Django

```bash
# Migrations
docker compose exec web python manage.py migrate

# Collecter les fichiers statiques
docker compose exec web python manage.py collectstatic --noinput

# Créer un superutilisateur
docker compose exec web python manage.py createsuperuser

# Shell Django
docker compose exec web python manage.py shell
```

---

## 6. Mise à jour

### Étape 1 : Sauvegarder les données

```bash
# Voir la section "Sauvegarde et restauration" ci-dessous
```

### Étape 2 : Mettre à jour le code

```bash
# Si vous utilisez Git
cd /opt/unabsences
git pull origin main

# OU copier les nouveaux fichiers manuellement
```

### Étape 3 : Reconstruire et redémarrer

```bash
# Reconstruire les images et redémarrer
docker compose up -d --build

# Exécuter les migrations si nécessaire
docker compose exec web python manage.py migrate
```

---

## 7. Dépannage

### Problème : Les conteneurs ne démarrent pas

```bash
# Vérifier les logs
docker compose logs

# Vérifier les erreurs de configuration
docker compose config
```

### Problème : Erreur de connexion à la base de données

```bash
# Vérifier que PostgreSQL est prêt
docker compose exec db pg_isready -U postgres

# Vérifier les variables d'environnement
docker compose exec web env | grep DB_
```

### Problème : Les fichiers statiques ne s'affichent pas

```bash
# Recollecter les fichiers statiques
docker compose exec web python manage.py collectstatic --noinput

# Redémarrer Nginx
docker compose restart nginx
```

### Problème : Erreur 502 Bad Gateway

```bash
# Vérifier que Gunicorn fonctionne
docker compose exec web ps aux | grep gunicorn

# Vérifier les logs de Nginx
docker compose logs nginx

# Vérifier les logs de l'application
docker compose logs web
```

### Problème : Port 80 déjà utilisé

```bash
# Vérifier quel processus utilise le port 80
sudo lsof -i :80

# Arrêter le service (ex: Apache)
sudo systemctl stop apache2
```

---

## 8. Configuration HTTPS (optionnel)

### Étape 1 : Installer Certbot

```bash
apt install -y certbot python3-certbot-nginx
```

### Étape 2 : Obtenir un certificat SSL

```bash
# Arrêter temporairement Nginx
docker compose stop nginx

# Obtenir le certificat
certbot certonly --standalone -d votre-domaine.com -d www.votre-domaine.com

# Les certificats seront dans : /etc/letsencrypt/live/votre-domaine.com/
```

### Étape 3 : Configurer Nginx pour HTTPS

1. **Modifier `nginx/nginx.conf`** :
   - Décommenter le bloc `server` pour HTTPS (port 443)
   - Configurer les chemins vers les certificats
   - Ajouter la redirection HTTP → HTTPS

2. **Copier les certificats dans le conteneur** :
   ```bash
   # Créer un volume pour les certificats
   # Modifier docker-compose.yml pour monter /etc/letsencrypt
   ```

3. **Redémarrer Nginx** :
   ```bash
   docker compose restart nginx
   ```

**📌 IMPORTANT POUR LA SOUTENANCE :**
- HTTPS est recommandé en production pour la sécurité
- Les certificats Let's Encrypt sont gratuits et renouvelables automatiquement
- Configurez un renouvellement automatique avec cron

---

## 9. Sauvegarde et restauration

### Sauvegarde de la base de données

```bash
# Créer un répertoire pour les sauvegardes
mkdir -p /opt/unabsences/backups

# Sauvegarder la base de données
docker compose exec db pg_dump -U postgres unabsences_db > /opt/unabsences/backups/backup_$(date +%Y%m%d_%H%M%S).sql

# OU depuis l'extérieur du conteneur
docker compose exec -T db pg_dump -U postgres unabsences_db > /opt/unabsences/backups/backup_$(date +%Y%m%d_%H%M%S).sql
```

### Sauvegarde des fichiers média

```bash
# Sauvegarder le volume media
docker run --rm -v unabsences_media_volume:/data -v /opt/unabsences/backups:/backup alpine tar czf /backup/media_$(date +%Y%m%d_%H%M%S).tar.gz /data
```

### Script de sauvegarde automatique

Créer un script `/opt/unabsences/backup.sh` :

```bash
#!/bin/bash
BACKUP_DIR="/opt/unabsences/backups"
DATE=$(date +%Y%m%d_%H%M%S)

# Sauvegarder la base de données
docker compose exec -T db pg_dump -U postgres unabsences_db > "$BACKUP_DIR/db_$DATE.sql"

# Sauvegarder les fichiers média
docker run --rm -v unabsences_media_volume:/data -v "$BACKUP_DIR":/backup alpine tar czf "/backup/media_$DATE.tar.gz" /data

# Supprimer les sauvegardes de plus de 30 jours
find "$BACKUP_DIR" -name "*.sql" -mtime +30 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +30 -delete

echo "Sauvegarde terminée : $DATE"
```

Rendre le script exécutable et l'ajouter au cron :

```bash
chmod +x /opt/unabsences/backup.sh

# Éditer le crontab
crontab -e

# Ajouter une ligne pour une sauvegarde quotidienne à 2h du matin
0 2 * * * /opt/unabsences/backup.sh >> /opt/unabsences/backups/backup.log 2>&1
```

### Restauration de la base de données

```bash
# Restaurer depuis un fichier de sauvegarde
docker compose exec -T db psql -U postgres unabsences_db < /opt/unabsences/backups/backup_20250101_120000.sql
```

---

## 📌 Points importants pour la soutenance

1. **Architecture Docker** :
   - 3 services : web (Django), db (PostgreSQL), nginx (reverse proxy)
   - Volumes persistants pour les données
   - Réseau Docker isolé pour la sécurité

2. **Sécurité** :
   - Variables d'environnement pour les secrets
   - Utilisateur non-root dans les conteneurs
   - Configuration HTTPS recommandée

3. **Performance** :
   - Nginx sert directement les fichiers statiques
   - Gunicorn avec plusieurs workers
   - Compression Gzip activée

4. **Maintenance** :
   - Sauvegardes automatiques
   - Logs centralisés
   - Commandes Docker simples pour la gestion

---

## 🆘 Support

En cas de problème :
1. Vérifier les logs : `docker compose logs`
2. Vérifier le statut : `docker compose ps`
3. Consulter la documentation Docker : https://docs.docker.com/

---

**✅ Votre application est maintenant déployée en production !**
