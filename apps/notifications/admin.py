"""
FICHIER : apps/notifications/admin.py
RESPONSABILITE : Configuration admin Django pour les notifications
"""
from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    """Configuration admin Django pour le modèle ``Notification`` (liste, filtres, préchargement)."""

    list_display = ("id_utilisateur", "message", "type", "lue", "date_envoi")
    list_select_related = ("id_utilisateur",)
    list_filter = ("lue", "type", "date_envoi")
