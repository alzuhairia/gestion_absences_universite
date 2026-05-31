"""
Sérialiseur de notification pour l'API REST UniAbsences.

Ce module fournit ``NotificationSerializer``, un sérialiseur sans modèle en
lecture seule utilisé par le point de terminaison de liste des notifications.
Tous les champs sont marqués en lecture seule car les notifications sont
créées en interne par le système (signaux, appels de services) et ne sont
jamais écrites via l'API.

Partie de l'API REST UniAbsences.
"""
from rest_framework import serializers


class NotificationSerializer(serializers.Serializer):
    """
    Représentation en lecture seule d'une notification utilisateur.

    Tous les champs sont en lecture seule — les notifications sont créées par
    des signaux internes et des appels de services, et non par les
    consommateurs de l'API.
    """

    id_notification = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    lue = serializers.BooleanField(read_only=True)
    date_envoi = serializers.DateTimeField(read_only=True)
