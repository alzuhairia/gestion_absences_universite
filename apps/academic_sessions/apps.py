"""
AppConfig pour l'application Django academic_sessions d'UniAbsences.

Le ``label = "academic_sessions"`` explicite résout un conflit de nommage
qui surviendrait sinon lorsque Django enregistre deux applications dont
les noms de package partagent un suffixe commun. Toutes les déclarations
``app_label`` des modèles de ce package utilisent ``"academic_sessions"``
pour correspondre.

Fait partie de la structure académique d'UniAbsences.
"""

from django.apps import AppConfig


class AcademicSessionsConfig(AppConfig):
    """
    Configuration de l'application Django pour le package academic_sessions.

    Attributs
    ---------
    default_auto_field : str
        Utilise ``BigAutoField`` comme type de clé primaire implicite pour
        tous les modèles qui n'en déclarent pas explicitement.
    name : str
        Chemin complet du module Python utilisé par le registre d'apps de Django.
    label : str
        Label court et unique qui distingue cette application des autres
        dont les noms de package pourraient entrer en conflit selon la
        dérivation de label par défaut de Django.
    verbose_name : str
        Nom lisible affiché dans l'en-tête du site d'administration Django.
    """

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.academic_sessions"
    # Le label explicite évite les conflits dans le registre d'apps avec des apps de noms similaires
    label = "academic_sessions"
    verbose_name = "Sessions Académiques"
