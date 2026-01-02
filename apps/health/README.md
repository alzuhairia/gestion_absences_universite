# App Health - Endpoint de Monitoring

## Description

Cette app Django fournit un endpoint de health check (`/api/health/`) pour le monitoring de l'application.

## Endpoint

### GET `/api/health/`

Vérifie que l'application Django et la base de données PostgreSQL sont opérationnelles.

**Réponse en cas de succès (HTTP 200):**
```json
{
  "status": "ok"
}
```

**Réponse en cas d'erreur (HTTP 503):**
```json
{
  "status": "error",
  "error": "message d'erreur"
}
```

## Caractéristiques

- ✅ **Accessible sans authentification** : Aucune connexion requise
- ✅ **CSRF exempt** : Utilise `@csrf_exempt` pour permettre les requêtes depuis les outils de monitoring
- ✅ **Méthode GET uniquement** : Utilise `@require_http_methods(["GET"])`
- ✅ **Vérification de la base de données** : Teste la connexion PostgreSQL
- ✅ **Réponse JSON simple** : Format minimal pour les outils de monitoring

## Utilisation

### Test avec curl

```bash
# Depuis l'extérieur du conteneur
curl http://localhost/api/health/

# Depuis le réseau Docker (depuis un autre conteneur)
curl http://web:8000/api/health/
```

### Test avec Uptime Kuma

Configurer un monitor HTTP(s) avec :
- **URL** : `http://web:8000/api/health/` (depuis le réseau Docker)
- **Type** : HTTP(s)
- **Nom** : "API Django - Health Check"

## Structure de l'app

```
apps/health/
├── __init__.py
├── admin.py
├── apps.py
├── urls.py
├── views.py
└── README.md
```

## Intégration

L'app est intégrée dans :
- `config/settings.py` : Ajoutée dans `INSTALLED_APPS`
- `config/urls.py` : Route `/api/` inclut `apps.health.urls`
- `apps/accounts/middleware.py` : `/api/health/` exclu de la vérification de changement de mot de passe

---

**Créé pour le système de monitoring Uptime Kuma**
