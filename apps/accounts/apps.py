# apps/accounts/apps.py
from django.apps import AppConfig

class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.accounts'
    label = 'accounts'  # <--- AJOUTE CETTE LIGNE (très important pour les migrations)
    verbose_name = 'Gestion des utilisateurs'
    
    def ready(self):
        """Import des signaux quand l'app est prête"""
        try:
            import apps.accounts.signals
        except ImportError:
            pass