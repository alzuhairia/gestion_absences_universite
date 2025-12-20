from django.contrib import admin
from .models import Notification

@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id_utilisateur', 'message', 'type', 'lue', 'date_envoi')
    list_filter = ('lue', 'type', 'date_envoi')