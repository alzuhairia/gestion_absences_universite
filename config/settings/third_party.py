"""
Third-party package configuration: DRF, drf-spectacular, email.
"""

import os

from .env import env_bool, env_int

# ─────────────────────────────────────────────────────────────────────────── #
#  DJANGO REST FRAMEWORK                                                      #
# ─────────────────────────────────────────────────────────────────────────── #

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.api.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "50/hour",
        "user": "500/hour",
        "absence_write": "60/hour",
        "justification_upload": "20/hour",
    },
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

# ─────────────────────────────────────────────────────────────────────────── #
#  DRF-SPECTACULAR (Swagger / OpenAPI)                                        #
# ─────────────────────────────────────────────────────────────────────────── #

SPECTACULAR_SETTINGS = {
    "TITLE": "UniAbsences API",
    "DESCRIPTION": "REST API pour le système de gestion des absences universitaires.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": r"/api/v1/",
}

# ─────────────────────────────────────────────────────────────────────────── #
#  EMAIL (SMTP)                                                               #
#                                                                             #
#  Development (default): emails print to terminal, no SMTP needed.          #
#  Production (Gmail SMTP): set these in .env:                               #
#    EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend               #
#    EMAIL_HOST=smtp.gmail.com                                               #
#    EMAIL_PORT=587                                                           #
#    EMAIL_USE_TLS=True                                                      #
#    EMAIL_HOST_USER=your_gmail@gmail.com                                    #
#    EMAIL_HOST_PASSWORD=xxxx xxxx xxxx xxxx  (Gmail App Password)           #
#    DEFAULT_FROM_EMAIL=UniAbsences <your_gmail@gmail.com>                   #
# ─────────────────────────────────────────────────────────────────────────── #

EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")

# Auto-detect backend: use SMTP only when credentials are actually provided.
_email_backend_env = os.getenv("EMAIL_BACKEND", "").strip()
if _email_backend_env:
    EMAIL_BACKEND = _email_backend_env
elif EMAIL_HOST_USER and EMAIL_HOST_PASSWORD:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
else:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)

DEFAULT_FROM_EMAIL = os.getenv(
    "DEFAULT_FROM_EMAIL",
    f"UniAbsences Notification System <{EMAIL_HOST_USER}>"
    if EMAIL_HOST_USER
    else "UniAbsences Notification System <noreply@uniabsences.local>",
)
