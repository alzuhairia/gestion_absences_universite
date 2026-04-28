"""
Core Django settings: installed apps, middleware, templates, database,
cache, authentication, internationalisation, and static files.
"""

import os

from django.contrib.messages import constants as message_constants

from .env import BASE_DIR, DEBUG, env_bool, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  APPLICATIONS INSTALLÉES                                                    #
# ─────────────────────────────────────────────────────────────────────────── #

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts",
    "apps.academics",
    "apps.enrollments",
    "apps.academic_sessions",
    "apps.absences",
    "apps.messaging",
    "apps.notifications",
    "apps.dashboard",
    "apps.audits",
    "apps.health",
    "apps.api",
    "rest_framework",
    "django_filters",
    "drf_spectacular",
    "crispy_forms",
    "crispy_bootstrap5",
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
    "apps.accounts.middleware.SessionInactivityMiddleware",
    "apps.accounts.middleware_2fa.TwoFactorMiddleware",
    "apps.accounts.middleware.RoleMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "csp.middleware.CSPMiddleware",
]

ROOT_URLCONF = "config.urls"

# ─────────────────────────────────────────────────────────────────────────── #
#  TEMPLATES                                                                  #
# ─────────────────────────────────────────────────────────────────────────── #

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.messaging.context_processors.unread_messages_count",
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
        "CONN_MAX_AGE": env_int("CONN_MAX_AGE", 0 if DEBUG else 600),
    }
}

# ─────────────────────────────────────────────────────────────────────────── #
#  CACHE (Redis / LocMem)                                                     #
# ─────────────────────────────────────────────────────────────────────────── #

from django.core.exceptions import ImproperlyConfigured  # noqa: E402

CACHE_BACKEND = os.getenv("CACHE_BACKEND", "redis").strip().lower()
if CACHE_BACKEND not in {"redis", "locmem"}:
    raise ImproperlyConfigured("CACHE_BACKEND must be one of: redis, locmem.")
if not DEBUG and CACHE_BACKEND != "redis":
    raise ImproperlyConfigured("CACHE_BACKEND=locmem is not allowed when DEBUG=False.")

if CACHE_BACKEND == "locmem":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unabsences-local-cache",
            "TIMEOUT": env_int("REDIS_CACHE_TIMEOUT", 300),
        }
    }
else:
    REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "").strip()
    if not DEBUG and not REDIS_PASSWORD:
        raise ImproperlyConfigured("REDIS_PASSWORD is required when DEBUG=False.")

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
                    "max_connections": env_int("REDIS_MAX_CONNECTIONS", 100),
                    "retry_on_timeout": True,
                },
            },
            "TIMEOUT": env_int("REDIS_CACHE_TIMEOUT", 300),
        }
    }

# ─────────────────────────────────────────────────────────────────────────── #
#  VALIDATION MOTS DE PASSE                                                   #
# ─────────────────────────────────────────────────────────────────────────── #

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
    {
        "NAME": "apps.accounts.validators.SystemSettingsPasswordValidator",
    },
]

# ─────────────────────────────────────────────────────────────────────────── #
#  INTERNATIONALISATION ET FICHIERS                                           #
# ─────────────────────────────────────────────────────────────────────────── #

LANGUAGE_CODE = "fr"
TIME_ZONE = "Europe/Brussels"
DEFAULT_CHARSET = "utf-8"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# ─────────────────────────────────────────────────────────────────────────── #
#  AUTHENTIFICATION ET SESSIONS                                               #
# ─────────────────────────────────────────────────────────────────────────── #

AUTH_USER_MODEL = "accounts.User"
DEFAULT_AUTO_FIELD = "django.db.models.AutoField"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "accounts:login"

# Token validity period in seconds (default: 1 hour).
PASSWORD_RESET_TIMEOUT = env_int("PASSWORD_RESET_TIMEOUT", 3600)

# Absolute max lifetime of a session cookie (seconds). Default: 30 min.
SESSION_COOKIE_AGE = env_int("SESSION_COOKIE_AGE", 1800)

# Also expire the session when the browser window is closed.
SESSION_EXPIRE_AT_BROWSER_CLOSE = True

# Reset the expiry countdown on every request (sliding window).
SESSION_SAVE_EVERY_REQUEST = True

# Inactivity timeout (seconds) enforced by middleware. Default: 15 min.
SESSION_INACTIVITY_TIMEOUT = env_int("SESSION_INACTIVITY_TIMEOUT", 900)

# Map Django message levels to Bootstrap alert CSS classes.
MESSAGE_TAGS = {
    message_constants.DEBUG: "secondary",
    message_constants.INFO: "info",
    message_constants.SUCCESS: "success",
    message_constants.WARNING: "warning",
    message_constants.ERROR: "danger",
}
