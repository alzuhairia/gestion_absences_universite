"""
Configuration de l'application Django pour l'app api.

Déclare l'AppConfig ``ApiConfig`` que Django charge lorsque ``apps.api``
est présent dans ``INSTALLED_APPS``. L'app api ne contient pas de
modèles propres ; elle expose la couche REST DRF construite au-dessus
des modèles des autres apps.

Fait partie du système de gestion des absences UniAbsences.
"""

from django.apps import AppConfig


class ApiConfig(AppConfig):
    """AppConfig pour l'API REST (DRF)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.api"
    label = "api"
    verbose_name = "API REST"
