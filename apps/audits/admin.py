from django.contrib import admin
from .models import LogAudit

@admin.register(LogAudit)
class LogAuditAdmin(admin.ModelAdmin):
    # Les colonnes à afficher dans la liste
    list_display = ('id_utilisateur', 'action', 'date_action', 'adresse_ip')
    
    # Ajouter des filtres pour retrouver facilement les blocages
    list_filter = ('date_action', 'id_utilisateur')
    
    # Barre de recherche pour chercher par action ou par étudiant
    search_fields = ('action', 'id_utilisateur__nom', 'id_utilisateur__prenom')
    
    # On rend les logs en lecture seule (un log d'audit ne doit jamais être modifié !)
    readonly_fields = ('id_utilisateur', 'action', 'date_action', 'adresse_ip')

    # Empêcher la suppression manuelle pour garantir l'intégrité (Option Jury +++)
    def has_delete_permission(self, request, obj=None):
        return False