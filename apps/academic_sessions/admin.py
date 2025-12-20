from django.contrib import admin
from .models import AnneeAcademique, Seance

@admin.register(AnneeAcademique)
class AnneeAcademiqueAdmin(admin.ModelAdmin):
    list_display = ('libelle', 'active')
    list_editable = ('active',) # Permet de cocher "active" directement dans la liste

@admin.register(Seance)
class SeanceAdmin(admin.ModelAdmin):
    list_display = ('id_cours', 'date_seance', 'heure_debut', 'heure_fin', 'id_annee')
    list_filter = ('id_annee', 'date_seance', 'id_cours')
    date_hierarchy = 'date_seance' # Ajoute une barre de navigation par date en haut