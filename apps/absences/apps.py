"""
FICHIER : apps/absences/apps.py
RESPONSABILITE : Configuration de l'app absences avec import des signaux
"""
from django.apps import AppConfig


class AbsencesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.absences"

    def ready(self):
        import apps.absences.signals
