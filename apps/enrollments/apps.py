"""
Configuration de l'application Django pour l'application enrollments.

Déclare l'AppConfig ``EnrollmentsConfig`` que Django charge lorsque le
label ``apps.enrollments`` est présent dans ``INSTALLED_APPS``.

Appartient à : UniAbsences — application enrollments.
"""

from django.apps import AppConfig


class EnrollmentsConfig(AppConfig):
    """Configuration de l'application Django pour le package enrollments."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.enrollments"
    label = "enrollments"
    verbose_name = "Inscriptions"
