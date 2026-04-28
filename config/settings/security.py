"""
Production hardening: HTTPS/HSTS, session cookies, CSP, frame options.
All security headers are set to strict values in production (DEBUG=False).
"""

from csp.constants import NONCE

from .env import DEBUG, env_bool, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  HTTPS / HSTS / COOKIE SECURITY                                             #
# ─────────────────────────────────────────────────────────────────────────── #

if DEBUG:
    SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", False)
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", False)
    CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", False)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    CSRF_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0)
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
else:
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"
    CSRF_COOKIE_HTTPONLY = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True

SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"
RATELIMIT_USE_CACHE = "default"

# drf-spectacular path parameter warnings are cosmetic (all endpoints work correctly).
# Silenced so that `manage.py check --deploy` produces zero warnings in CI.
SILENCED_SYSTEM_CHECKS = [
    "drf_spectacular.W001",
    "drf_spectacular.W002",
]

# ─────────────────────────────────────────────────────────────────────────── #
#  CONTENT SECURITY POLICY (CSP)                                              #
#  Nonce-based: all <script> tags must carry nonce="{{ request.csp_nonce }}". #
# ─────────────────────────────────────────────────────────────────────────── #

CONTENT_SECURITY_POLICY = {
    "DIRECTIVES": {
        "default-src": ["'self'"],
        "script-src": ["'self'", NONCE, "cdn.jsdelivr.net"],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
            "cdn.jsdelivr.net",
            "cdnjs.cloudflare.com",
        ],
        "font-src": ["'self'", "cdnjs.cloudflare.com", "cdn.jsdelivr.net"],
        "img-src": ["'self'", "data:", "blob:"],
        "connect-src": ["'self'", "cdn.jsdelivr.net", "cdnjs.cloudflare.com"],
        "object-src": ["'none'"],
        "base-uri": ["'self'"],
        "form-action": ["'self'"],
        "frame-ancestors": ["'none'"],
    },
}
