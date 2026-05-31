"""
Configuration de l'application Django pour le dashboard UniAbsences.

Ce module enregistre l'application ``dashboard`` auprès du registre
d'applications de Django. L'application dashboard est le hub central du
système : elle gère la logique de redirection par rôle, le modèle singleton
``SystemSettings``, toutes les vues admin/secrétariat/professeur/étudiant
et la couche partagée de décorateurs.

Partie du système dashboard UniAbsences.
"""

from django.apps import AppConfig


class DashboardConfig(AppConfig):
    """
    AppConfig pour l'application ``dashboard``.

    Enregistre l'application sous le label ``dashboard`` et définit le type
    de champ auto par défaut à ``BigAutoField`` pour tous les modèles définis
    ici.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.dashboard"
