"""
Environment parsing helpers, fundamental security primitives, and load_dotenv.
Imported first by every other settings sub-module.
"""

import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# config/settings/env.py → config/settings/ → config/ → project root
BASE_DIR = Path(__file__).resolve().parent.parent.parent

load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)


# ─────────────────────────────────────────────────────────────────────────── #
#  HELPERS DE PARSING ENVIRONNEMENT                                           #
# ─────────────────────────────────────────────────────────────────────────── #

def env_bool(name: str, default: bool = False) -> bool:
    """Parse une variable d'environnement comme booléen (1/true/yes/on)."""
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """Parse une variable d'environnement comme entier."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be an integer.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    """Parse une variable d'environnement comme liste séparée par virgules."""
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_cidr_list(name: str, default: str = "") -> list[str]:
    """Parse une liste de blocs CIDR avec validation IP."""
    values = env_list(name, default)
    for cidr in values:
        try:
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ImproperlyConfigured(f"{name} contains invalid CIDR: {cidr}") from exc
    return values


# ─────────────────────────────────────────────────────────────────────────── #
#  SÉCURITÉ FONDAMENTALE                                                      #
# ─────────────────────────────────────────────────────────────────────────── #

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
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}  # nosec B104
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
