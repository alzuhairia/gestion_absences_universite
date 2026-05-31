"""
Durcissement sécurité production pour le projet UniAbsences.

Configure :
  - Redirection HTTPS et HSTS (HTTP Strict Transport Security).
  - Drapeaux Secure et HttpOnly sur les cookies de session et CSRF.
  - Politique de cookies SameSite (Strict en production, Lax en développement).
  - En-têtes de sécurité divers (COEP, X-Frame-Options, Referrer-Policy).
  - Sélection du backend cache pour le rate-limit.
  - Content Security Policy (basée sur des nonces) via django-csp.

En développement (DEBUG=True), la plupart des réglages de durcissement sont
assouplis ou rendus configurables via variables d'environnement pour que les
workflows locaux (HTTP non chiffré, outils de dev navigateur) ne soient pas
entravés.

En production (DEBUG=False), tous les réglages sont verrouillés sur leurs
valeurs les plus sécurisées, indépendamment de toute surcharge par variable
d'environnement.

Fait partie du package settings de UniAbsences.
"""

from csp.constants import NONCE

from .env import DEBUG, env_bool, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  HTTPS / HSTS / SÉCURITÉ DES COOKIES                                        #
# ─────────────────────────────────────────────────────────────────────────── #

if DEBUG:
    # Développement : autorise HTTP non chiffré ; les drapeaux de sécurité sont opt-in via variables d'env.
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    # Lax autorise l'envoi du cookie de session sur les navigations top-level cross-site
    # (par ex. en suivant un lien externe vers le site), ce qui est acceptable en développement.
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_HTTPONLY = True
    # HSTS désactivé par défaut en développement pour éviter de mettre en cache
    # accidentellement l'en-tête dans le navigateur pour une longue durée.
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
else:
    # Production : tous les drapeaux de sécurité sont obligatoires et non surchargeables.
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True   # Cookie envoyé uniquement via HTTPS.
    CSRF_COOKIE_SECURE = True      # Jeton CSRF envoyé uniquement via HTTPS.
    SESSION_COOKIE_HTTPONLY = True  # Cookie inaccessible au JavaScript.
    # Strict empêche l'envoi du cookie sur toute requête cross-site, offrant la
    # protection CSRF la plus forte au prix de l'UX sur les liens externes.
    SESSION_COOKIE_SAMESITE = "Strict"
    CSRF_COOKIE_HTTPONLY = True    # Le cookie CSRF est également masqué au JavaScript.
    # HSTS d'1 an avec sous-domaines + preload — indique aux navigateurs d'utiliser toujours HTTPS.
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

# Empêche les navigateurs de deviner par MIME-sniffing un type de contenu différent de celui déclaré.
SECURE_CONTENT_TYPE_NOSNIFF = True

# Cross-Origin Opener Policy : isole le contexte de navigation des openers
# cross-origin (atténue les attaques par canal auxiliaire de type Spectre via la mémoire partagée).
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"

# Empêche le site d'être intégré dans <frame>, <iframe> ou <object> depuis n'importe quelle origine.
X_FRAME_OPTIONS = "DENY"

# Supprime l'en-tête Referer complet sur les navigations cross-origin.
SECURE_REFERRER_POLICY = "same-origin"

# Utilise le backend cache Django par défaut (Redis en production) pour les compteurs de rate-limit.
RATELIMIT_USE_CACHE = "default"

# Les avertissements de paramètres de chemin de drf-spectacular sont cosmétiques (tous les endpoints fonctionnent).
# Réduits au silence pour que `manage.py check --deploy` produise zéro avertissement en CI.
SILENCED_SYSTEM_CHECKS = [
    "drf_spectacular.W001",
    "drf_spectacular.W002",
]

# ─────────────────────────────────────────────────────────────────────────── #
#  CONTENT SECURITY POLICY (CSP)                                              #
#  Basée sur des nonces : chaque balise <script> doit porter nonce="{{ request.csp_nonce }}".#
# ─────────────────────────────────────────────────────────────────────────── #

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        # Par défaut, ne charge les ressources que depuis cette origine.
        "default-src": ["'self'"],
        # Scripts : même origine + nonce CSP (scripts inline) + CDN jsdelivr.
        # La constante NONCE est remplacée au moment de la requête par django-csp.
        "script-src": ["'self'", NONCE, "cdn.jsdelivr.net"],
        # Styles : même origine + styles inline (Bootstrap l'exige) + CDNs.
        "style-src": [
            "'self'",
            "'unsafe-inline'",     # Bootstrap applique des styles dynamiquement.
            "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com",
        ],
        # Polices web : même origine + CDNs hébergeant les polices d'icônes (Font Awesome, etc.).
        "font-src": ["'self'", "cdnjs.cloudflare.com", "cdn.jsdelivr.net"],
        # Images : même origine + URIs data (les QR codes sont des URIs data en base64) + blobs.
        "img-src": ["'self'", "data:", "blob:"],
        # XHR/fetch : même origine + CDNs pour les requêtes de vérification de version.
        "connect-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
        # Bloque tout contenu de plugin (Flash, applets Java, etc.).
        "object-src": ["'none'"],
        # Empêche les attaques par détournement de balise base.
        "base-uri": ["'self'"],
        # Les formulaires ne peuvent soumettre qu'à la même origine.
        "form-action": ["'self'"],
        # Équivalent à X_FRAME_OPTIONS=DENY mais imposé via CSP.
        "frame-ancestors": ["'none'"],
    },
}
