"""
Configuration de l'admin Django pour l'application academic_sessions d'UniAbsences.

Enregistre ``AnneeAcademique`` et ``Seance`` auprès du site d'administration
Django. La liste ``AnneeAcademique`` permet de basculer l'indicateur
``active`` directement en ligne ; la liste ``Seance`` expose une navigation
hiérarchique par date ainsi que des filtres pour un parcours efficace des
grands ensembles de séances.

Fait partie de la structure académique d'UniAbsences.
"""

from django.contrib import admin

from .models import AnneeAcademique, Seance


@admin.register(AnneeAcademique)
class AnneeAcademiqueAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle AnneeAcademique (année académique).

    ``list_editable`` sur la colonne ``active`` permet aux administrateurs
    d'activer ou désactiver une année directement depuis la vue liste sans
    ouvrir le formulaire de détail. Notez que l'enregistrement d'une
    activation déclenche ``AnneeAcademique.save()``, qui désactive de
    manière atomique toutes les autres années et peut clôturer les
    inscriptions étudiantes ouvertes.
    """

    list_display = ("libelle", "active")
    # Permet de basculer l'indicateur actif directement dans la liste de modification
    list_editable = ("active",)


@admin.register(Seance)
class SeanceAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle Seance (séance de cours).

    ``date_hierarchy`` ajoute une barre de navigation hiérarchique
    année/mois/jour en haut de la liste, facilitant le parcours des
    séances par date à travers de grands ensembles de données.
    """

    list_display = ("id_cours", "date_seance", "heure_debut", "heure_fin", "id_annee")
    list_filter = ("id_annee", "date_seance", "id_cours")
    # Navigation hiérarchique par date (année → mois → jour)
    date_hierarchy = "date_seance"
