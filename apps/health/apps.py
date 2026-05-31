"""
Configuration de l'application Django pour l'app de health check.

Déclare l'AppConfig ``HealthConfig`` que Django charge lorsque
``apps.health`` est présent dans ``INSTALLED_APPS``.

Appartient à : UniAbsences — app health.
"""
from django.apps import AppConfig


class HealthConfig(AppConfig):
    """AppConfig pour l'endpoint de monitoring de health check."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.health"
    verbose_name = "Health Check"
