"""
AppConfig de l'application Django audits dans UniAbsences.

Déclare la configuration de l'application que Django découvre via le
mécanisme ``default_app_config``. Le label ``audits`` est utilisé dans
le champ ``app_label`` du modèle ``LogAudit`` et dans les déclarations
de namespace d'URL.

Fait partie du système d'audit UniAbsences.
"""

from django.apps import AppConfig


class AuditsConfig(AppConfig):
    """
    Configuration de l'application Django pour le package audits.

    Attributs
    ---------
    default_auto_field : str
        Utilise ``BigAutoField`` comme type implicite de clé primaire pour
        tous les modèles qui n'en déclarent pas explicitement.
    name : str
        Chemin complet du module Python (``apps.audits``) utilisé par le
        registre d'applications de Django pour localiser les modèles, les
        migrations et les signaux.
    """

    default_auto_field = "django.db.models.BigAutoField"
    # Le chemin pointé complet correspond à l'emplacement du package sous le répertoire apps/
    name = "apps.audits"
