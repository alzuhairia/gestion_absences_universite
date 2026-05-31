"""
Settings Django principaux pour le projet UniAbsences.

Couvre : applications installées, pile de middleware, moteur de templates,
base de données PostgreSQL, backend de cache Redis/LocMem, validateurs de
mot de passe, internationalisation, chemins des fichiers static et media,
comportement des sessions, et redirections d'authentification.

Dépend de : config/settings/env.py (BASE_DIR, DEBUG, env_int doivent être
importés avant le chargement de ce module).

Fait partie du package settings de UniAbsences.
"""

import os

from django.contrib.messages import constants as message_constants

from .env import BASE_DIR, DEBUG, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  APPLICATIONS INSTALLÉES                                                    #
# ─────────────────────────────────────────────────────────────────────────── #

INSTALLED_APPS = [
    # Applications intégrées à Django
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Applications métier de UniAbsences
    "apps.accounts",           # Modèle utilisateur personnalisé, auth, 2FA, rôles
    "apps.academics",          # Facultés, départements, cours
    "apps.enrollments",        # Inscriptions étudiantes et règles d'éligibilité
    "apps.academic_sessions",  # Années académiques et séances (cours)
    "apps.absences",           # Saisie d'absences, justification, présence par QR
    "apps.messaging",          # Messagerie interne entre utilisateurs
    "apps.notifications",      # Infrastructure de notifications par email
    "apps.dashboard",          # Vues du tableau de bord selon le rôle et paramètres système
    "apps.audits",             # Visualiseur du journal d'audit de l'administration
    "apps.health",             # Endpoint de monitoring /api/health/
    "apps.api",                # API REST DRF (v1)
    # Bibliothèques tierces
    "rest_framework",          # Django REST Framework
    "django_filters",          # Filtrage par chaîne de requête pour les viewsets DRF
    "drf_spectacular",         # Génération du schéma OpenAPI 3 (Swagger UI)
    "crispy_forms",            # Helpers de rendu de formulaires
    "crispy_bootstrap5",       # Pack de templates Bootstrap 5 pour crispy_forms
]

# ─────────────────────────────────────────────────────────────────────────── #
#  MIDDLEWARE                                                                 #
# ─────────────────────────────────────────────────────────────────────────── #

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    # Personnalisé : déconnecte les utilisateurs inactifs après SESSION_INACTIVITY_TIMEOUT secondes.
    "apps.accounts.middleware.SessionInactivityMiddleware",
    # Personnalisé : bloque l'accès à toutes les vues derrière la vérification 2FA lorsque l'utilisateur a activé la 2FA.
    "apps.accounts.middleware_2fa.TwoFactorMiddleware",
    # Personnalisé : attache le rôle de l'utilisateur à la requête pour utilisation dans les templates et les vues.
    "apps.accounts.middleware.RoleMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # django-csp : émet l'en-tête Content-Security-Policy sur chaque réponse.
    "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

# ─────────────────────────────────────────────────────────────────────────── #
#  TEMPLATES                                                                  #
# ─────────────────────────────────────────────────────────────────────────── #

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Répertoire de templates au niveau projet (a priorité sur les templates au niveau application).
        "DIRS": [BASE_DIR / "templates"],
        # Recherche aussi les templates dans le répertoire templates/ de chaque application installée.
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                # Injecte unread_messages_count dans chaque contexte de template.
                "apps.messaging.context_processors.unread_messages_count",
                # Injecte le drapeau active_qr_session pour la bannière de présence QR.
                "apps.absences.context_processors.active_qr_session",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# ─────────────────────────────────────────────────────────────────────────── #
#  BASE DE DONNÉES (PostgreSQL)                                               #
# ─────────────────────────────────────────────────────────────────────────── #

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "gestion_absences_universite"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
        # Connexions persistantes : 0 en développement (nouvelle connexion par requête),
        # 600 s (10 min) en production pour réduire le surcoût d'établissement de connexion.
        "CONN_MAX_AGE": env_int("CONN_MAX_AGE", 0 if DEBUG else 600),
    }
}

# ─────────────────────────────────────────────────────────────────────────── #
#  CACHE (Redis en production, LocMem en développement)                       #
# ─────────────────────────────────────────────────────────────────────────── #

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

CACHE_BACKEND = os.getenv("CACHE_BACKEND", "redis").strip().lower()
if CACHE_BACKEND not in {"redis", "locmem"}:
    raise ImproperlyConfigured("CACHE_BACKEND doit valoir l'une des options : redis, locmem.")
# LocMem est un cache en mémoire de processus qui ne partage pas son état entre workers —
# il est explicitement interdit en production où plusieurs processus s'exécutent.
if not DEBUG and CACHE_BACKEND != "redis":
    raise ImproperlyConfigured("CACHE_BACKEND=locmem est interdit lorsque DEBUG=False.")

if CACHE_BACKEND == "locmem":
    # Cache de développement à processus unique — aucune dépendance externe requise.
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unabsences-local-cache",
            "TIMEOUT": env_int("REDIS_CACHE_TIMEOUT", 300),
        }
    }
else:
    # Cache Redis — le mot de passe est obligatoire en production pour prévenir les attaques de serveur ouvert.
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "").strip()
    if not DEBUG and not REDIS_PASSWORD:
        raise ImproperlyConfigured("REDIS_PASSWORD est requis lorsque DEBUG=False.")

    # Construit l'URL Redis à partir des composants si elle n'est pas fournie explicitement.
    REDIS_URL = os.getenv("REDIS_URL", "").strip()
    if not REDIS_URL:
        if REDIS_PASSWORD:
            REDIS_URL = f"redis://:{REDIS_PASSWORD}@redis:6379/1"
        else:
            REDIS_URL = "redis://redis:6379/1"

    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "CONNECTION_POOL_KWARGS": {
                    # Plafonne le nombre total de connexions Redis pour prévenir l'épuisement du pool sous charge.
                    "max_connections": env_int("REDIS_MAX_CONNECTIONS", 100),
                    # Réessaie automatiquement en cas de timeouts réseau transitoires.
                    "retry_on_timeout": True,
                },
            },
            "TIMEOUT": env_int("REDIS_CACHE_TIMEOUT", 300),
        }
    }

# ─────────────────────────────────────────────────────────────────────────── #
#  VALIDATION DES MOTS DE PASSE                                               #
# ─────────────────────────────────────────────────────────────────────────── #

AUTH_PASSWORD_VALIDATORS = [
    # Rejette les mots de passe trop similaires aux attributs de l'utilisateur (email, nom).
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    # Impose une longueur minimale de mot de passe (par défaut Django : 8 caractères).
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    # Rejette les mots de passe figurant dans la liste des mots de passe communs de Django.
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    # Rejette les mots de passe entièrement numériques.
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    # Validateur personnalisé : lit les règles de complexité depuis SystemSettings
    # (niveau de complexité, longueur minimale, exigences de chiffres/majuscules/caractères spéciaux).
    {
        "NAME": "apps.accounts.validators.SystemSettingsPasswordValidator",
    },
]

# ─────────────────────────────────────────────────────────────────────────── #
#  INTERNATIONALISATION ET CHEMINS DE FICHIERS                                #
# ─────────────────────────────────────────────────────────────────────────── #

LANGUAGE_CODE = "fr"           # Libellés UI en français (admin Django, erreurs de formulaire, etc.)
TIME_ZONE = "Europe/Brussels"  # Tous les datetimes naïfs sont interprétés dans ce fuseau horaire.
DEFAULT_CHARSET = "utf-8"
USE_I18N = True                # Active la machinerie de traduction de Django.
USE_TZ = True                  # Stocke en interne tous les datetimes en UTC.

# Fichiers statiques collectés par `collectstatic` dans STATIC_ROOT pour le serveur web.
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

# Fichiers téléversés par les utilisateurs (documents de justification, photos de profil).
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# ─────────────────────────────────────────────────────────────────────────── #
#  CONFIGURATION DE L'AUTHENTIFICATION ET DES SESSIONS                        #
# ─────────────────────────────────────────────────────────────────────────── #

# Remplace le modèle User par celui personnalisé qui utilise l'email comme identifiant de connexion.
AUTH_USER_MODEL = "accounts.User"
# Utilise des clés primaires entières pour tous les modèles qui ne spécifient pas explicitement une PK.
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

# Noms d'URL utilisés par le décorateur login_required de Django et les redirections de login/logout.
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "accounts:login"

# Durée de validité du token en secondes (par défaut : 1 heure).
# Contrôle la durée pendant laquelle les liens de réinitialisation de mot de passe restent utilisables.
PASSWORD_RESET_TIMEOUT = env_int("PASSWORD_RESET_TIMEOUT", 3600)

# Durée de vie absolue maximale d'un cookie de session (secondes). Par défaut : 30 min.
# Le timeout d'inactivité à fenêtre glissante (SESSION_INACTIVITY_TIMEOUT) est
# généralement plus court, donc le cookie atteint rarement sa durée de vie complète.
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 1800)

# Expire également la session à la fermeture de la fenêtre du navigateur (pas de cookie persistant).
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Réinitialise le compte à rebours d'expiration à chaque requête (fenêtre glissante).
# Sans cela, la session expirerait après une durée fixe à compter du login.
SESSION_SAVE_EVERY_REQUEST = True

# Timeout d'inactivité (secondes) appliqué par SessionInactivityMiddleware.
# Par défaut : 15 min. Plus court que SESSION_COOKIE_AGE pour détecter les onglets inactifs.
SESSION_INACTIVITY_TIMEOUT = env_int("SESSION_INACTIVITY_TIMEOUT", 900)

# Associe les constantes de niveau de message Django aux noms de classes CSS d'alerte Bootstrap 5
# afin que {% for message in messages %} affiche des alertes correctement stylisées.
MESSAGE_TAGS = {
    message_constants.DEBUG: "secondary",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}
