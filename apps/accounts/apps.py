"""
AppConfig pour l'application accounts de UniAbsences.

Ce module définit ``AccountsConfig``, la classe de configuration d'application
Django pour le package ``apps.accounts``. Elle définit le label de
l'application, le nom lisible par les humains et le type de champ de clé
primaire par défaut utilisé pour tout modèle dont la classe ``Meta`` ne le
spécifie pas explicitement.

Le hook ``ready`` est fourni comme un emplacement vide ; importez ici les
gestionnaires de signaux (par exemple ``import apps.accounts.signals``)
lorsque des récepteurs sont ajoutés à ``signals.py``.

Fait partie du système accounts de UniAbsences.
"""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """
    AppConfig Django pour l'application accounts.

    Attributs :
        default_auto_field (str): Utilise ``BigAutoField`` afin que toutes les
            clés primaires générées automatiquement soient des entiers 64
            bits, cohérent avec le reste du projet.
        name (str): Chemin Python pointé utilisé par le registre d'apps de Django.
        label (str): Label court utilisé pour le namespace des migrations et de l'admin.
        verbose_name (str): Nom lisible affiché dans l'admin Django.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    label = "accounts"
    verbose_name = "Gestion des utilisateurs"

    def ready(self):
        """
        Exécute la logique de démarrage après que le registre d'applications est entièrement peuplé.

        Actuellement sans effet. Placez ici les imports de récepteurs de
        signaux lorsque des gestionnaires sont ajoutés à
        ``apps/accounts/signals.py`` afin de garantir qu'ils sont connectés
        avant le traitement de toute requête.
        """
        pass
