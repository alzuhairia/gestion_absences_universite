"""
Configuration de l'administration Django pour l'application academics dans UniAbsences.

Enregistre les trois modèles centraux de la structure académique — ``Faculte``,
``Departement`` et ``Cours`` — auprès du site d'administration Django, en
fournissant des affichages de liste adaptés à la navigation administrative
quotidienne.

Partie de la structure académique d'UniAbsences.
"""

from django.contrib import admin

from .models import Cours, Departement, Faculte


@admin.register(Faculte)
class FaculteAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle Faculte (faculté).

    Affiche la clé primaire et le nom de la faculté dans la liste de
    modification afin que les administrateurs puissent rapidement identifier
    et naviguer vers une faculté spécifique.
    """

    list_display = ("id_faculte", "nom_faculte")


@admin.register(Departement)
class DepartementAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle Departement.

    Affiche l'identifiant du département, son nom et sa faculté parente afin
    que la hiérarchie à trois niveaux (faculté → département → cours) soit
    immédiatement visible dans la vue en liste.
    """

    list_display = ("id_departement", "nom_departement", "id_faculte")


@admin.register(Cours)
class CoursAdmin(admin.ModelAdmin):
    """
    Interface d'administration pour le modèle Cours.

    Affiche le code unique du cours, son nom complet et le département
    propriétaire. Le code du cours est l'identifiant principal lisible par
    l'humain utilisé dans tout le système pour les rapports et les exports.
    """

    list_display = ("code_cours", "nom_cours", "id_departement")
