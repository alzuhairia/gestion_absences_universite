from django.contrib import admin
from .models import Inscription

@admin.register(Inscription)
class InscriptionAdmin(admin.ModelAdmin):
    # Colonnes à afficher dans la liste
    list_display = ('id_etudiant', 'id_cours', 'id_annee', 'type_inscription', 'eligible_examen')
    # Filtres sur le côté droit
    list_filter = ('id_annee', 'type_inscription', 'eligible_examen', 'id_cours')
    # Barre de recherche (cherche par nom d'étudiant ou nom de cours)
    search_fields = ('id_etudiant__nom', 'id_etudiant__prenom', 'id_cours__nom_cours')