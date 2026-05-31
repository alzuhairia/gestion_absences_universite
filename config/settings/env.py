"""
Helpers de parsing d'environnement, primitives de sécurité fondamentales et chargement dotenv.

Ce module est importé en premier par tous les autres sous-modules de settings.
Il est responsable de :
  - Résoudre ``BASE_DIR`` (la racine du projet).
  - Charger ``.env`` et ``.env.local`` via python-dotenv.
  - Fournir des helpers typés pour lire les variables d'environnement (bool, int,
    list, liste CIDR).
  - Imposer les variables de sécurité obligatoires (SECRET_KEY, ALLOWED_HOSTS, etc.)
    qui rendraient l'application non sécurisée ou non fonctionnelle si elles
    étaient absentes.
  - Configurer le modèle de confiance proxy (X-Forwarded-Proto / X-Forwarded-Host).
  - Exposer les chaînes de rate-limit centralisées consommées par django-ratelimit.

Fait partie du package settings de UniAbsences.
"""

import ipaddress
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Résout la racine du projet : config/settings/env.py → config/settings/ → config/ → racine
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Charge d'abord .env, puis laisse .env.local surcharger les valeurs individuelles.
# Les deux fichiers sont optionnels — un fichier manquant est silencieusement ignoré par load_dotenv.
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR / ".env.local", override=True)


# ─────────────────────────────────────────────────────────────────────────── #
#  HELPERS DE PARSING D'ENVIRONNEMENT                                         #
# ─────────────────────────────────────────────────────────────────────────── #

def env_bool(name: str, default: bool = False) -> bool:
    """
    Analyse une variable d'environnement comme un booléen.

    Valeurs vraies acceptées (insensible à la casse) : ``1``, ``true``, ``yes``, ``on``.
    Toute autre chaîne non vide est traitée comme ``False``.

    Parameters:
        name (str): Nom de la variable d'environnement.
        default (bool): Valeur retournée lorsque la variable n'est pas définie.

    Returns:
        bool: Valeur booléenne analysée ou ``default``.
    """
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    """
    Analyse une variable d'environnement comme un entier.

    Parameters:
        name (str): Nom de la variable d'environnement.
        default (int): Valeur retournée lorsque la variable n'est pas définie.

    Returns:
        int: Valeur entière analysée ou ``default``.

    Raises:
        ImproperlyConfigured: Si la variable est définie mais ne peut être
            convertie en entier.
    """
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} doit être un entier.") from exc


def env_list(name: str, default: str = "") -> list[str]:
    """
    Analyse une variable d'environnement séparée par des virgules en liste de chaînes nettoyées.

    Les segments vides (ex. virgules en fin) sont supprimés.

    Parameters:
        name (str): Nom de la variable d'environnement.
        default (str): Valeur par défaut brute séparée par des virgules,
            utilisée lorsque la variable n'est pas définie.

    Returns:
        list[str]: Liste des valeurs non vides, nettoyées.
    """
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def env_cidr_list(name: str, default: str = "") -> list[str]:
    """
    Analyse une liste séparée par des virgules de blocs réseau CIDR avec validation IP.

    Parameters:
        name (str): Nom de la variable d'environnement.
        default (str): Valeur par défaut brute séparée par des virgules,
            utilisée lorsque la variable n'est pas définie.

    Returns:
        list[str]: Chaînes CIDR validées (ex. ``["10.0.0.0/8", "::1/128"]``).

    Raises:
        ImproperlyConfigured: Si l'une des valeurs n'est pas un réseau IP
            valide en notation CIDR.
    """
    values = env_list(name, default)
    for cidr in values:
        try:
            # strict=False permet aux bits hôtes d'être positionnés (ex. 192.168.1.1/24).
            ipaddress.ip_network(cidr, strict=False)
        except ValueError as exc:
            raise ImproperlyConfigured(f"{name} contient un CIDR invalide : {cidr}") from exc
    return values


# ─────────────────────────────────────────────────────────────────────────── #
#  RÉGLAGES DE SÉCURITÉ FONDAMENTAUX                                          #
# ─────────────────────────────────────────────────────────────────────────── #

# DEBUG doit être False en production — False est le défaut sécurisé.
DEBUG = env_bool("DEBUG", False)

# SECRET_KEY est obligatoire : Django l'utilise pour les jetons CSRF, la
# signature de session, les jetons de reset de mot de passe et d'autres
# opérations cryptographiques.
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ImproperlyConfigured("La variable d'environnement SECRET_KEY est requise.")

# Clés placeholder connues que les développeurs laissent souvent par inadvertance.
# Rejet immédiat en production pour éviter une compromission cryptographique.
INSECURE_SECRET_KEYS = {
    "change-me",
    "insecure-dev-key",
    "replace-with-a-long-random-secret",
    "django-insecure-dev-key",
}
if not DEBUG and SECRET_KEY in INSECURE_SECRET_KEYS:
    raise ImproperlyConfigured("SECRET_KEY n'est pas sécurisée pour la production.")

# Jeton bearer du health-check envoyé dans l'en-tête X-Healthcheck-Token.
# Requis en production pour que l'endpoint ne soit pas accessible publiquement.
HEALTHCHECK_TOKEN = os.getenv("HEALTHCHECK_TOKEN", "").strip()
if not DEBUG and not HEALTHCHECK_TOKEN:
    raise ImproperlyConfigured("HEALTHCHECK_TOKEN est requis lorsque DEBUG=False.")

# Prend en charge la rotation de jeton : une liste de jetons précédemment valides
# est acceptée pendant la fenêtre de rotation pour que les agents de monitoring
# n'aient pas besoin de se mettre à jour simultanément.
HEALTHCHECK_TOKEN_PREVIOUS = env_list("HEALTHCHECK_TOKEN_PREVIOUS", "")
HEALTHCHECK_VALID_TOKENS = [HEALTHCHECK_TOKEN, *HEALTHCHECK_TOKEN_PREVIOUS]

# ALLOWED_HOSTS restreint les en-têtes HTTP Host que Django acceptera.
# Doit contenir au moins une entrée pour empêcher les attaques par injection d'en-tête Host.
ALLOWED_HOSTS = [
    h.strip() for h in os.getenv("ALLOWED_HOSTS", "").split(",") if h.strip()
]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured("ALLOWED_HOSTS doit être défini avec au moins un hôte.")

# CSRF_TRUSTED_ORIGINS : origines acceptées pour les soumissions de formulaires cross-origin.
# En production, dérive automatiquement depuis ALLOWED_HOSTS si non défini explicitement.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]
if not DEBUG and not CSRF_TRUSTED_ORIGINS:
    # Inclut uniquement les vrais noms d'hôte — exclut les adresses loopback.
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host not in {"localhost", "127.0.0.1", "0.0.0.0"}  # nosec B104
    ]

# Lorsque l'application tourne derrière un reverse proxy (Nginx/Traefik), fait
# confiance à l'en-tête X-Forwarded-Proto pour déterminer le schéma d'origine.
USE_X_FORWARDED_PROTO = env_bool("USE_X_FORWARDED_PROTO", True)
if USE_X_FORWARDED_PROTO:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Reste False par défaut pour éviter le spoofing du Host via les en-têtes forwardés.
# À activer uniquement si le proxy est de confiance et positionne Host correctement.
USE_X_FORWARDED_HOST = env_bool("USE_X_FORWARDED_HOST", False)

# TRUSTED_PROXY_CIDRS : seules les requêtes provenant de ces CIDRs sont autorisées
# à positionner les en-têtes proxy (X-Forwarded-For, X-Forwarded-Proto, etc.).
# Obligatoire en production pour empêcher le spoofing d'IP par des clients non fiables.
if not DEBUG and os.getenv("TRUSTED_PROXY_CIDRS") is None:
    raise ImproperlyConfigured(
        "TRUSTED_PROXY_CIDRS doit être défini explicitement lorsque DEBUG=False."
    )
TRUSTED_PROXY_CIDRS = env_cidr_list("TRUSTED_PROXY_CIDRS", "127.0.0.1/32,::1/128")
if not DEBUG and not TRUSTED_PROXY_CIDRS:
    raise ImproperlyConfigured("TRUSTED_PROXY_CIDRS doit être défini lorsque DEBUG=False.")

# HEALTHCHECK_ALLOWLIST_CIDRS : seules les requêtes dont l'IP *client* (après extraction
# proxy) correspond à l'un de ces CIDRs peuvent appeler /api/health/.
# Obligatoire en production pour restreindre l'endpoint santé aux agents de monitoring.
if not DEBUG and os.getenv("HEALTHCHECK_ALLOWLIST_CIDRS") is None:
    raise ImproperlyConfigured(
        "HEALTHCHECK_ALLOWLIST_CIDRS doit être défini explicitement lorsque DEBUG=False."
    )
HEALTHCHECK_ALLOWLIST_CIDRS = env_cidr_list(
    "HEALTHCHECK_ALLOWLIST_CIDRS", "127.0.0.1/32,::1/128"
)
if not DEBUG and not HEALTHCHECK_ALLOWLIST_CIDRS:
    raise ImproperlyConfigured(
        "HEALTHCHECK_ALLOWLIST_CIDRS doit être défini lorsque DEBUG=False."
    )

# Chaînes de rate-limit centralisées, pilotées par environnement et consommées par django-ratelimit.
# Format : "<nombre>/<période>" où la période est s/m/h/d.
HEALTHCHECK_RATE_LIMIT = os.getenv("HEALTHCHECK_RATE_LIMIT", "12/m")
LOGIN_RATE_LIMIT_IP = os.getenv("LOGIN_RATE_LIMIT_IP", "20/5m")
LOGIN_RATE_LIMIT_COMBINED = os.getenv("LOGIN_RATE_LIMIT_COMBINED", "5/5m")
