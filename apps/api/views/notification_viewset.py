"""
Viewset des notifications pour l'API REST UniAbsences.

``NotificationViewSet`` fournit des opérations de lecture et de marquage
comme lu sur le modèle ``Notification``. Les notifications sont générées
en interne par le système (signaux, appels de service) et ne sont jamais
créées via l'API.

Endpoints :
  - GET  /notifications/             : liste les notifications de l'utilisateur
                                       authentifié, plus récentes en premier.
  - POST /notifications/{id}/mark_read/   : marque une notification individuelle comme lue.
  - POST /notifications/mark_all_read/    : marque en masse toutes les notifications non lues comme lues.

Partie de l'API REST UniAbsences.
"""

from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from django.shortcuts import get_object_or_404

from apps.notifications.models import Notification

from ..pagination import StandardPagination
from ..serializers import NotificationSerializer


@extend_schema_view(
    list=extend_schema(summary="List my notifications", tags=["Notifications"]),
    mark_read=extend_schema(summary="Mark notification as read", tags=["Notifications"]),
    mark_all_read=extend_schema(summary="Mark all notifications as read", tags=["Notifications"]),
)
class NotificationViewSet(viewsets.GenericViewSet, mixins.ListModelMixin):
    """Notifications de l'utilisateur (auto-générées par le système)."""

    serializer_class = NotificationSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = StandardPagination

    def get_queryset(self):  # type: ignore[override]
        """Restreint le queryset aux notifications de l'utilisateur connecté, plus récentes d'abord."""
        if getattr(self, "swagger_fake_view", False):
            return Notification.objects.none()
        return Notification.objects.filter(
            id_utilisateur=self.request.user
        ).order_by("-date_envoi")

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        """Marque une notification spécifique comme lue (404 si elle n'appartient pas à l'appelant)."""
        notif = get_object_or_404(
            Notification, pk=pk, id_utilisateur=request.user
        )
        notif.lue = True
        notif.save(update_fields=["lue"])
        return Response({"status": "read"})

    @action(detail=False, methods=["post"])
    def mark_all_read(self, request):
        """Marque toutes les notifications non lues de l'utilisateur comme lues, en une requête."""
        count = Notification.objects.filter(
            id_utilisateur=request.user, lue=False
        ).update(lue=True)
        return Response({"marked_read": count})
