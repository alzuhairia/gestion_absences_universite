# 📊 Système de Monitoring - UniAbsences

## 🎯 Pourquoi le monitoring est important ?

Dans un contexte professionnel et académique, la disponibilité de l'application est **critique**. Les étudiants, professeurs et secrétaires dépendent de l'application pour gérer les absences quotidiennement. Un système de monitoring permet de :

- **Détecter rapidement les pannes** : Savoir immédiatement si l'application est inaccessible
- **Assurer la continuité de service** : Réagir rapidement en cas de problème
- **Démontrer la professionnalisation** : Montrer que l'application est prête pour un environnement de production
- **Prévenir plutôt que guérir** : Identifier les problèmes avant qu'ils n'affectent les utilisateurs

## 🛠️ Pourquoi Uptime Kuma ?

**Uptime Kuma** a été choisi pour plusieurs raisons :

### ✅ Simplicité
- **Interface web intuitive** : Pas besoin de configuration complexe
- **Déploiement rapide** : Une seule commande Docker pour démarrer
- **Aucune dépendance lourde** : Solution légère et performante

### ✅ Professionnalisme
- **Open-source et gratuit** : Solution reconnue dans l'industrie
- **Fonctionnalités complètes** : Monitoring HTTP, TCP, DNS, etc.
- **Historique et statistiques** : Visualisation claire de la disponibilité

### ✅ Compatibilité
- **Docker natif** : S'intègre parfaitement avec l'architecture existante
- **Indépendant** : N'affecte pas les performances de l'application principale
- **Réseau Docker** : Peut surveiller les services internes (base de données, API)

### ✅ Présentation académique
- **Interface claire** : Facile à démontrer lors de la soutenance
- **Données visuelles** : Graphiques et statistiques compréhensibles
- **Prêt à l'emploi** : Configuration minimale requise

## 📦 Ce qui est surveillé

Le système de monitoring surveille les composants critiques de l'application :

### 🌐 Site web principal (via Nginx)
- **Type** : HTTP/HTTPS
- **URL** : `http://nginx/accounts/login/` (depuis le réseau Docker)
- **Alternative externe** : `http://localhost/accounts/login/` (depuis l'extérieur)
- **Objectif** : Vérifier que l'interface web est accessible via le reverse proxy
- **Fréquence** : Vérification toutes les minutes
- **Note** : Utilisez `nginx` (nom du service) si Uptime Kuma est dans le même réseau Docker

### ⚙️ API Django (directement)
- **Type** : HTTP
- **URL** : `http://web:8000/api/health/` (depuis le réseau Docker)
- **Alternative externe** : `http://localhost/api/health/` (depuis l'extérieur)
- **Objectif** : Vérifier que l'API Django fonctionne et que la base de données est connectée
- **Fréquence** : Vérification toutes les minutes
- **Endpoint** : Retourne un JSON avec le statut de l'application et de la base de données
- **Note** : Utilisez `web:8000` (nom du service + port) si Uptime Kuma est dans le même réseau Docker

### 🐘 Base de données PostgreSQL
- **Type** : TCP
- **Host** : `db` (nom du service Docker)
- **Port** : `5432`
- **Objectif** : Vérifier que PostgreSQL est accessible et répond
- **Fréquence** : Vérification toutes les minutes
- **Note** : Utilisez `db` (nom du service) car Uptime Kuma est dans le même réseau Docker

## 🚀 Installation et utilisation

### Prérequis
- Docker et Docker Compose installés
- L'application principale doit être démarrée (pour que le réseau Docker existe)

### Démarrage du monitoring

```bash
# Démarrer le service de monitoring
docker compose -f docker-compose.monitoring.yml up -d
```

### Accès à l'interface

Une fois démarré, accédez à l'interface Uptime Kuma :
- **URL** : `http://localhost:3001`
- **Première connexion** : Créer un compte administrateur lors du premier accès

### Configuration des surveillances

1. **Créer un nouveau monitor** dans l'interface Uptime Kuma
2. **Configurer les surveillances** (utilisez les noms de services Docker) :
   - **Site web** : Type "HTTP(s)", URL `http://nginx/accounts/login/`
   - **API Django** : Type "HTTP(s)", URL `http://web:8000/api/health/`
   - **PostgreSQL** : Type "TCP Port", Host `db`, Port `5432`

**⚠️ Important** : Comme Uptime Kuma est dans le même réseau Docker (`unabsences_network`), utilisez les noms de services (`nginx`, `web`, `db`) et non `localhost`.

### Arrêt du monitoring

```bash
# Arrêter le service
docker compose -f docker-compose.monitoring.yml down

# Arrêter et supprimer les données (⚠️ supprime l'historique)
docker compose -f docker-compose.monitoring.yml down -v
```

## 📊 Architecture technique

### Services Docker

Le monitoring utilise un fichier `docker-compose.monitoring.yml` **indépendant** de l'application principale :

```
┌─────────────────────────────────────┐
│      Uptime Kuma (Monitoring)      │
│         Port: 3001                  │
│    Volume: uptime_kuma_data         │
└──────────────────┬──────────────────┘
                   │
                   │ Réseau Docker
                   │ (unabsences_network)
                   │
┌──────────────────▼──────────────────┐
│    Application principale           │
│  - Django (web)                     │
│  - PostgreSQL (db)                   │
│  - Nginx (nginx)                    │
└─────────────────────────────────────┘
```

### Volumes persistants

Les données de monitoring sont stockées dans un volume Docker :
- **Nom** : `uptime_kuma_data`
- **Contenu** : Configurations, historiques, statistiques
- **Persistance** : Les données sont conservées même si le conteneur est supprimé

### Réseau Docker

Le monitoring utilise le même réseau Docker que l'application principale (`unabsences_network`), ce qui permet de :
- Surveiller les services internes (base de données)
- Accéder aux services via leurs noms Docker (`web`, `db`, `nginx`)
- Maintenir l'isolation réseau

## 🎓 Présentation pour la soutenance

### Points à mettre en avant

1. **Professionnalisme** : Démontrer que l'application est prête pour la production
2. **Disponibilité** : Montrer que la supervision est en place
3. **Réactivité** : Expliquer comment les problèmes sont détectés rapidement
4. **Simplicité** : Souligner la facilité de déploiement et d'utilisation

### Démonstration recommandée

1. **Afficher l'interface Uptime Kuma** : Montrer les monitors configurés
2. **Démontrer une alerte** : Simuler une panne (arrêter un service) et montrer la détection
3. **Afficher les statistiques** : Montrer l'historique de disponibilité
4. **Expliquer l'endpoint de santé** : Montrer `http://localhost/api/health/` dans le navigateur

## 🔒 Sécurité

### Accès au monitoring

- **Interface** : Accessible uniquement en local (`localhost:3001`)
- **Authentification** : Compte administrateur créé lors de la première connexion
- **Isolation** : Service indépendant, aucun impact sur l'application principale

### Recommandations pour la production

En production, il est recommandé de :
- Protéger l'interface avec une authentification forte
- Utiliser HTTPS pour l'accès à Uptime Kuma
- Configurer des notifications (email, Slack, etc.) pour les alertes
- Limiter l'accès à l'interface de monitoring

## 📚 Ressources

- **Documentation Uptime Kuma** : https://github.com/louislam/uptime-kuma
- **Docker Compose** : Voir `docker-compose.monitoring.yml`
- **Endpoint de santé** : `http://localhost/api/health/` (voir `config/urls.py`)

## ✅ Checklist de déploiement

- [ ] Docker et Docker Compose installés
- [ ] Application principale démarrée (`docker compose up -d`)
- [ ] Monitoring démarré (`docker compose -f docker-compose.monitoring.yml up -d`)
- [ ] Interface accessible (`http://localhost:3001`)
- [ ] Compte administrateur créé
- [ ] Monitors configurés (Site web, API, Base de données)
- [ ] Tests de surveillance effectués
- [ ] Documentation lue et comprise

---

**🎉 Le système de monitoring est maintenant opérationnel !**

*Documentation créée pour la soutenance académique - Janvier 2025*
