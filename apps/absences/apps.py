"""
Configuration de l'application Django pour l'app absences.

Ce module définit la sous-classe AppConfig que Django utilise pour initialiser
l'application ``apps.absences``. Le hook ``ready()`` importe le module signals
afin que tous les décorateurs ``@receiver`` soient enregistrés auprès du
dispatcher de signaux de Django au démarrage de l'application.

Fait partie du système de gestion des absences UniAbsences.
"""
from django.apps import AppConfig


class AbsencesConfig(AppConfig):
    """
    AppConfig pour l'application absences.

    Définit le type de clé primaire par défaut à BigAutoField et garantit que
    les récepteurs de signaux définis dans ``apps.absences.signals`` sont
    connectés au démarrage de l'application via le hook ``ready()``.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.absences"

    def ready(self):
        """
        Connecte les récepteurs de signaux lorsque le registre des applications est entièrement peuplé.

        L'import de ``apps.absences.signals`` ici (dans ``ready()``) garantit
        que tous les décorateurs ``@receiver`` de ce module sont évalués après
        le chargement de tous les modèles, évitant ainsi les erreurs
        AppRegistryNotReady qui surviendraient si les signaux étaient importés
        au niveau du module.
        """
        import apps.absences.signals  # noqa: F401 — connecte les décorateurs @receiver
