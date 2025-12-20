def ready(self):
    try:
        import apps.accounts.signals  # L'erreur vient d'ici
    except ImportError:
        pass