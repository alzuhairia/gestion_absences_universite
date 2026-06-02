"""
Configuration de l'application Django pour l'app messaging.

Déclare l'AppConfig ``MessagingConfig`` que Django charge lorsque
``apps.messaging`` est présent dans ``INSTALLED_APPS``.

Fait partie du système de gestion des absences UniAbsences.
"""

from django.apps import AppConfig


class MessagingConfig(AppConfig):
    """AppConfig pour l'application messaging (messagerie interne)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"
    label = "messaging"
    verbose_name = "Messagerie interne"
