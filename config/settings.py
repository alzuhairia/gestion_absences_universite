import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Load base env, then optional local overrides (.env.local)
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_cidr_list(name: str, default: str = "") -> list[str]:
    values = env_list(name, default)
    for cidr in values:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ImproperlyConfigured(f"{name} contains invalid CIDR: {cidr}") from exc
    return values


# Core security settings
DEBUG = env_bool("DEBUG", False)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY environment variable is required.")
INSECURE_SECRET_KEYS = {
    "change-me",
    "insecure-dev-key",
    "replace-with-a-long-random-secret",
    "django-insecure-dev-key",
}
if not DEBUG and SECRET_KEY in INSECURE_SECRET_KEYS:
    raise ImproperlyConfigured("SECRET_KEY is insecure for production.")

HEALTHCHECK_TOKEN = os.getenv("HEALTHCHECK_TOKEN", "").strip()
if not DEBUG and not HEALTHCHECK_TOKEN:
    raise ImproperlyConfigured("HEALTHCHECK_TOKEN is required when DEBUG=False.")
HEALTHCHECK_TOKEN_PREVIOUS = env_list("HEALTHCHECK_TOKEN_PREVIOUS", "")
HEALTHCHECK_VALID_TOKENS = [HEALTHCHECK_TOKEN, *HEALTHCHECK_TOKEN_PREVIOUS]

ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS must be set with at least one host.")

CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if not DEBUG and not CSRF_TRUSTED_ORIGINS:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}
    ]

USE_X_FORWARDED_PROTO = env_bool("USE_X_FORWARDED_PROTO", True)
if USE_X_FORWARDED_PROTO:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Keep False by default to avoid host header spoofing via forwarded headers.
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", False)

# Trust proxy-provided client IP headers only when request comes from these CIDRs.
if not DEBUG and os.getenv("TRUSTED_PROXY_CIDRS") is None:
    raise ImproperlyConfigured(
        "TRUSTED_PROXY_CIDRS must be explicitly set when DEBUG=False."
    )
TRUSTED_PROXY_CIDRS = env_cidr_list("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
if not DEBUG and not TRUSTED_PROXY_CIDRS:
    raise ImproperlyConfigured("TRUSTED_PROXY_CIDRS must be set when DEBUG=False.")

# Allowlist for /api/health/ caller IPs (client IP after trusted-proxy extraction).
if not DEBUG and os.getenv("HEALTHCHECK_ALLOWLIST_CIDRS") is None:
    raise ImproperlyConfigured(
        "HEALTHCHECK_ALLOWLIST_CIDRS must be explicitly set when DEBUG=False."
    )
HEALTHCHECK_ALLOWLIST_CIDRS = env_cidr_list(
    "HEALTHCHECK_ALLOWLIST_CIDRS", "127.0.0.1/32,::1/128"
)
if not DEBUG and not HEALTHCHECK_ALLOWLIST_CIDRS:
    raise ImproperlyConfigured(
        "HEALTHCHECK_ALLOWLIST_CIDRS must be set when DEBUG=False."
    )

# Centralized, environment-driven rate limits
HEALTHCHECK_RATE_LIMIT = os.getenv("HEALTHCHECK_RATE_LIMIT", "12/m")
LOGIN_RATE_LIMIT_IP = os.getenv("LOGIN_RATE_LIMIT_IP", "20/5m")
LOGIN_RATE_LIMIT_COMBINED = os.getenv("LOGIN_RATE_LIMIT_COMBINED", "5/5m")


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
    "crispy_forms",
    "crispy_bootstrap5",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.accounts.middleware.RoleMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("DB_NAME", "gestion_absences_universite"),
        "USER": os.getenv("DB_USER", "postgres"),
        "PASSWORD": os.getenv("DB_PASSWORD", ""),
        "HOST": os.getenv("DB_HOST", "db"),
        "PORT": os.getenv("DB_PORT", "5432"),
    }
}

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

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "staticfiles")

MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

AUTH_USER_MODEL = "accounts.User"

LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "dashboard:index"
LOGOUT_REDIRECT_URL = "accounts:login"

LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOGS_DIR / "django.log",
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "verbose",
        },
        "console": {
            "level": "DEBUG" if DEBUG else "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console", "file"],
            "level": "DEBUG" if DEBUG else "INFO",
            "propagate": False,
        },
    },
}

# Production hardening
if DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
else:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = (
    "strict-origin-when-cross-origin" if not DEBUG else "same-origin"
)
RATELIMIT_USE_CACHE = "default"
