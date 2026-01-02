# 🚀 Guide de démarrage rapide - Monitoring

## Démarrage en 3 étapes

### Étape 1 : Démarrer l'application principale

```bash
docker compose up -d
```

Cette commande démarre :
- PostgreSQL (base de données)
- Django (application web)
- Nginx (reverse proxy)

**Important** : Cette étape crée le réseau Docker `unabsences_network` nécessaire pour le monitoring.

### Étape 2 : Démarrer le monitoring

```bash
docker compose -f docker-compose.monitoring.yml up -d
```

Cette commande démarre :
- Uptime Kuma (interface de monitoring)

### Étape 3 : Accéder à l'interface

1. Ouvrir votre navigateur
2. Aller à : `http://localhost:3001`
3. Créer un compte administrateur lors du premier accès

## Configuration des surveillances

**⚠️ IMPORTANT** : Uptime Kuma étant dans le même réseau Docker, utilisez les **noms de services Docker** et non `localhost`.

Une fois connecté à Uptime Kuma, ajouter les monitors suivants :

### 1. Site web principal (via Nginx)
- **Type** : HTTP(s)
- **URL** : `http://nginx/accounts/login/`
- **Nom** : "Site Web UniAbsences (Nginx)"
- **Note** : Surveille l'accès via le reverse proxy Nginx

### 2. API Django (directement)
- **Type** : HTTP(s)
- **URL** : `http://web:8000/api/health/`
- **Nom** : "API Django - Health Check"
- **Note** : Surveille directement l'application Django et la connexion à la base de données

### 3. Base de données PostgreSQL
- **Type** : TCP Port
- **Host** : `db`
- **Port** : `5432`
- **Nom** : "PostgreSQL Database"
- **Note** : Surveille la disponibilité de PostgreSQL

### Alternative : Monitoring externe (si besoin)

Si vous souhaitez surveiller depuis l'extérieur du réseau Docker (par exemple depuis votre machine), utilisez :

- **Site web** : `http://localhost/accounts/login/`
- **API Django** : `http://localhost/api/health/`
- **PostgreSQL** : `localhost:5432` (nécessite d'exposer le port dans docker-compose.yml)

## Vérification

Pour vérifier que tout fonctionne :

```bash
# Vérifier les conteneurs
docker compose ps
docker compose -f docker-compose.monitoring.yml ps

# Voir les logs
docker compose logs -f
docker compose -f docker-compose.monitoring.yml logs -f
```

## Arrêt

```bash
# Arrêter le monitoring
docker compose -f docker-compose.monitoring.yml down

# Arrêter l'application principale
docker compose down
```

## Dépannage

### Le monitoring ne peut pas se connecter au réseau

Si vous obtenez l'erreur : `network unabsences_network declared as external, but could not be found`

```bash
# Créer le réseau manuellement (une seule fois)
docker network create unabsences_network

# Puis redémarrer le monitoring
docker compose -f docker-compose.monitoring.yml up -d
```

**Note** : Si l'application principale est déjà démarrée, le réseau devrait exister. Si ce n'est pas le cas, créez-le manuellement comme ci-dessus.

### Le port 3001 est déjà utilisé

Si le port 3001 est occupé, modifier `docker-compose.monitoring.yml` :

```yaml
ports:
  - "3002:3001"  # Utiliser le port 3002 à la place
```

Puis accéder à `http://localhost:3002`

---

**✅ Tout est prêt ! Consultez MONITORING.md pour plus de détails.**
