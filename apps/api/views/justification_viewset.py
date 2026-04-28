"""
FICHIER : apps/api/views/justification_viewset.py
RESPONSABILITE : ViewSet pour la gestion des justificatifs.
  - Etudiant : soumettre et lister ses propres justificatifs
  - Admin/Secretaire : lister tous, approuver/rejeter via l'action 'process'
  - Professeur : lecture seule sur ses cours
"""
from typing import Type, Union, cast, Dict, Any

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.absences.models import Absence, Justification
from apps.accounts.models import User
from apps.notifications.email import (
    build_justification_decision_email,
    build_justification_decision_professor_email,
    build_justification_submitted_professor_email,
    send_notification_email,
)

from django.db import transaction
from django.utils import timezone

from ..filters import JustificationFilter
from ..pagination import StandardPagination
from ..permissions import IsAdminOrSecretary, IsStudent
from ..serializers import (
    JustificationCreateSerializer,
    JustificationListSerializer,
    JustificationProcessSerializer,
)


@extend_schema_view(
    list=extend_schema(summary="List justifications", tags=["Justifications"]),
    retrieve=extend_schema(summary="Get justification detail", tags=["Justifications"]),
    create=extend_schema(summary="Submit a justification (student only)", tags=["Justifications"]),
)
class JustificationViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """
    Justification management.

    - Student: create justifications for own absences, list own
    - Admin/Secretary: list all, approve/reject via process action
    - Professor: read-only for their courses
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = JustificationFilter
    ordering_fields = ["date_soumission", "state"]
    ordering = ["-date_soumission"]

    def get_throttles(self):
        if self.action == "create":
            from apps.api.throttles import JustificationUploadThrottle
            return [JustificationUploadThrottle()]
        return super().get_throttles()

    def get_permissions(self):
        if self.action == "create":
            return [IsStudent()]
        if self.action == "process":
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[JustificationCreateSerializer], Type[JustificationProcessSerializer], Type[JustificationListSerializer]]:  # type: ignore[override]
        if self.action == "create":
            return JustificationCreateSerializer
        if self.action == "process":
            return JustificationProcessSerializer
        return JustificationListSerializer

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return Justification.objects.none()
        qs = Justification.objects.select_related(
            "id_absence__id_inscription__id_etudiant",
            "id_absence__id_inscription__id_cours",
            "validee_par",
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            return qs.filter(
                id_absence__id_inscription__id_etudiant=user
            )
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(
                id_absence__id_inscription__id_cours__professeur=user
            )
        return qs

    def perform_create(self, serializer):
        with transaction.atomic():
            justification = serializer.save()
            absence = Absence.objects.select_for_update().get(
                pk=justification.id_absence_id
            )
            absence.statut = Absence.Statut.EN_ATTENTE
            absence.save(update_fields=["statut"])

        professor = absence.id_seance.id_cours.professeur
        if professor:
            subj, body, html_body = build_justification_submitted_professor_email(
                professor,
                self.request.user,
                absence.id_seance.id_cours.code_cours,
                str(absence.id_seance.date_seance),
            )
            send_notification_email(professor, subj, body, html_body=html_body)

    @extend_schema(
        summary="Approve or reject a justification",
        tags=["Justifications"],
        request=JustificationProcessSerializer,
        responses=JustificationListSerializer,
    )
    @action(detail=True, methods=["post"], url_path="process")
    def process(self, request, pk=None):
        """Approve or reject a justification."""
        serializer = JustificationProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = cast(Dict[str, Any], serializer.validated_data)
        action_value = validated_data["action"]
        comment = validated_data.get("commentaire_gestion", "")

        with transaction.atomic():
            justification = Justification.objects.select_for_update().get(
                pk=self.get_object().pk
            )
            absence = Absence.objects.select_for_update().get(
                pk=justification.id_absence_id
            )

            if justification.state != Justification.State.EN_ATTENTE:
                return Response(
                    {"detail": "This justification has already been processed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if action_value == "approve":
                justification.state = Justification.State.ACCEPTEE
                absence.statut = Absence.Statut.JUSTIFIEE
            else:
                justification.state = Justification.State.REFUSEE
                absence.statut = Absence.Statut.NON_JUSTIFIEE

            justification.validee_par = request.user
            justification.date_validation = timezone.now()
            justification.commentaire_gestion = comment
            justification.save()
            absence.save(update_fields=["statut"])

        student = absence.id_inscription.id_etudiant
        course_code = absence.id_seance.id_cours.code_cours
        date_str = str(absence.id_seance.date_seance)
        approved = action_value == "approve"

        subj, body, html_body = build_justification_decision_email(
            student, course_code, date_str, approved, comment
        )
        send_notification_email(student, subj, body, html_body=html_body)

        professor = absence.id_seance.id_cours.professeur
        if professor:
            subj, body, html_body = build_justification_decision_professor_email(
                professor, student, course_code, date_str, approved
            )
            send_notification_email(professor, subj, body, html_body=html_body)

        return Response(
            JustificationListSerializer(justification).data,
            status=status.HTTP_200_OK,
        )
