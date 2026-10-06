"""
FICHIER : apps/notifications/admin.py
RESPONSABILITE : Configuration admin Django pour les notifications
"""
from django.contrib import admin

from .models import EmailEnvoi, Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("id_utilisateur", "message", "type", "lue", "date_envoi")
    list_select_related = ("id_utilisateur",)
    list_filter = ("lue", "type", "date_envoi")


@admin.register(EmailEnvoi)
class EmailEnvoiAdmin(admin.ModelAdmin):
    """Historique en lecture seule : c'est une preuve d'envoi."""

    list_display = ("date_envoi", "destinataire_email", "sujet", "statut")
    list_filter = ("statut", "date_envoi")
    search_fields = ("destinataire_email", "sujet")
    readonly_fields = ("destinataire", "destinataire_email", "sujet", "statut", "date_envoi")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
