"""
FICHIER : apps/accounts/apps.py
RESPONSABILITE : Configuration de l'app accounts
"""
from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Gestion des utilisateurs"

    def ready(self):
        pass
