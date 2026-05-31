"""
Configuration des paquets tiers pour le projet UniAbsences.

Configure :
  - Django REST Framework (DRF) : authentification, permissions, pagination,
    filtrage, throttling et classe de schéma.
  - drf-spectacular : paramètres de génération du schéma OpenAPI 3 (titre,
    version, préfixe de chemin du schéma).
  - Backend email : sélection automatique entre console (développement) et SMTP
    (production) en fonction des identifiants disponibles dans l'environnement.

Fait partie du package settings de UniAbsences.
"""

import os

from .env import env_bool, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  DJANGO REST FRAMEWORK                                                      #
# ─────────────────────────────────────────────────────────────────────────── #

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # Authentification par session pour les clients navigateur (protégée par CSRF).
        "rest_framework.authentication.SessionAuthentication",
        # Authentification par jeton pour les clients programmatiques de l'API.
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        # Tous les endpoints nécessitent une authentification par défaut ; les vues
        # individuelles peuvent assouplir cela via l'attribut permission_classes.
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Classe de pagination personnalisée qui retourne page + count + liens next/previous.
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        # Filtrage par query string d'URL (par ex. ?statut=NON_JUSTIFIEE).
        "django_filters.rest_framework.DjangoFilterBackend",
        # Recherche plein texte via ?search=<terme>.
        "rest_framework.filters.SearchFilter",
        # Tri par colonne via ?ordering=<champ>.
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        # Rate-limit des appelants anonymes par adresse IP.
        "rest_framework.throttling.AnonRateThrottle",
        # Rate-limit des utilisateurs authentifiés par PK utilisateur.
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        # Quota global anonyme : 50 requêtes par heure et par IP.
        "anon": "50/hour",
        # Quota global authentifié : 500 requêtes par heure et par utilisateur.
        "user": "500/hour",
        # Scope personnalisé pour les écritures d'absences (marquage/édition/suppression).
        "absence_write": "60/hour",
        # Scope personnalisé pour les uploads de documents de justification.
        "justification_upload": "20/hour",
    },
    # Utilise l'AutoSchema de drf-spectacular pour la génération automatique du spec OpenAPI.
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ─────────────────────────────────────────────────────────────────────────── #
#  DRF-SPECTACULAR (Swagger / OpenAPI 3)                                      #
# ─────────────────────────────────────────────────────────────────────────── #

SPECTACULAR_SETTINGS = {
    "TITLE": "UniAbsences API",
    "DESCRIPTION": "API REST pour le système de gestion des absences universitaires.",
    "VERSION": "1.0.0",
    # Ne pas exposer l'endpoint de téléchargement du schéma brut dans Swagger UI.
    "SERVE_INCLUDE_SCHEMA": False,
    # Génère des schémas de requête et de réponse séparés pour les endpoints où ils diffèrent.
    "COMPONENT_SPLIT_REQUEST": True,
    # Supprime ce préfixe des chemins affichés dans Swagger UI.
    "SCHEMA_PATH_PREFIX": r"/api/v1/",
}

# ─────────────────────────────────────────────────────────────────────────── #
#  EMAIL (SMTP / Console)                                                     #
#                                                                             #
#  Défaut en développement : les emails sont affichés dans le terminal.       #
#  Production (Gmail SMTP) : configurez les variables suivantes dans .env :   #
#    EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend               #
#    EMAIL_HOST=smtp.gmail.com                                               #
#    EMAIL_PORT=587                                                           #
#    EMAIL_USE_TLS=True                                                      #
#    EMAIL_HOST_USER=your_gmail@gmail.com                                    #
#    EMAIL_HOST_PASSWORD=xxxx xxxx xxxx xxxx  (mot de passe d'application Gmail)#
#    DEFAULT_FROM_EMAIL=UniAbsences <your_gmail@gmail.com>                   #
# ─────────────────────────────────────────────────────────────────────────── #

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

# Détection automatique du backend email :
#   1. Utilise la valeur de la variable d'env EMAIL_BACKEND si elle est définie explicitement.
#   2. Utilise SMTP lorsque l'utilisateur et le mot de passe sont tous deux fournis.
#   3. Bascule sur le backend console (affiche sur stdout) pour le développement.
_email_backend_env = os.getenv("EMAIL_BACKEND", "").strip()
if _email_backend_env:
    EMAIL_BACKEND = _email_backend_env
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
# Utilise STARTTLS (port 587) plutôt que TLS implicite (port 465).
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

# Construit l'adresse "From" par défaut à partir du compte expéditeur configuré,
# ou bascule sur une adresse locale générique lorsqu'on tourne sans SMTP.
DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    f"UniAbsences Notification System <{EMAIL_HOST_USER}>"
    if EMAIL_HOST_USER
    else "UniAbsences Notification System <noreply@uniabsences.local>",
)
