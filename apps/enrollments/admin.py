"""
Configuration de l'admin Django pour l'application enrollments.

Enregistre le modèle ``Inscription`` avec un ``ModelAdmin`` personnalisé qui
expose les colonnes d'affichage de la liste, les filtres latéraux et une
barre de recherche adaptée au workflow quotidien du secrétariat (retrouver
les inscriptions d'un étudiant par nom ou cours).

Appartient à : UniAbsences — application enrollments.
"""
from django.contrib import admin

from .models import Inscription


@admin.register(Inscription)
class InscriptionAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle Inscription.

    Fournit des colonnes, des filtres et une recherche pour aider les
    administrateurs à localiser et inspecter rapidement les inscriptions
    des étudiants aux cours.
    """

    # Colonnes affichées dans le tableau de la liste de modifications.
    list_display = (
        "id_etudiant",
        "id_cours",
        "id_annee",
        "type_inscription",
        "eligible_examen",
    )
    # Pré-chargement des objets liés via une seule jointure pour éviter les requêtes N+1.
    list_select_related = ("id_etudiant", "id_cours", "id_annee")
    # Widgets de filtres latéraux pour restreindre la liste des inscriptions.
    list_filter = ("id_annee", "type_inscription", "eligible_examen", "id_cours")
    # Barre de recherche : permet la recherche par nom, prénom de l'étudiant ou nom du cours.
    search_fields = ("id_etudiant__nom", "id_etudiant__prenom", "id_cours__nom_cours")
