"""
AppConfig pour l'application Django academics dans UniAbsences.

L'étiquette ``academics`` est utilisée dans toutes les déclarations
``app_label`` des modèles au sein de ce package, et ``verbose_name``
fournit le nom lisible par l'humain affiché dans l'administration.

Partie de la structure académique d'UniAbsences.
"""

from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    """Configuration de l'application Django pour le package academics."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academics"
    label = "academics"
    verbose_name = "Structure académique"
