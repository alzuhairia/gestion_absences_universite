"""
FICHIER : apps/api/serializers/notification_serializers.py
RESPONSABILITE : Serializer DRF pour les notifications utilisateur.
"""
from rest_framework import serializers


class NotificationSerializer(serializers.Serializer):
    id_notification = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    lue = serializers.BooleanField(read_only=True)
    date_envoi = serializers.DateTimeField(read_only=True)
