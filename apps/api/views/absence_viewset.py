"""
FICHIER : apps/api/views/absence_viewset.py
RESPONSABILITE : ViewSet CRUD pour les absences.
  - Admin/Secretaire : acces complet
  - Professeur : creation/modification sur ses cours
  - Etudiant : lecture seule de ses propres absences
"""
from typing import Any, Dict, Type, Union, cast

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription

from ..filters import AbsenceFilter
from ..pagination import StandardPagination
from ..permissions import IsAdminOrSecretary, IsAdminOrSecretaryOrProfessor
from ..serializers import AbsenceListSerializer, AbsenceWriteSerializer


@extend_schema_view(
    list=extend_schema(summary="List absences", tags=["Absences"]),
    retrieve=extend_schema(summary="Get absence detail", tags=["Absences"]),
    create=extend_schema(summary="Record an absence", tags=["Absences"]),
    update=extend_schema(summary="Update absence", tags=["Absences"]),
    partial_update=extend_schema(summary="Partial update absence", tags=["Absences"]),
    destroy=extend_schema(summary="Delete absence", tags=["Absences"]),
)
class AbsenceViewSet(viewsets.ModelViewSet):
    """
    CRUD for absences.

    - Admin/Secretary: full access
    - Professor: create/update/list for their courses
    - Student: read-only for own absences
    """

    pagination_class = StandardPagination

    def get_throttles(self):
        if self.action in ("create", "update", "partial_update"):
            from apps.api.throttles import AbsenceWriteThrottle
            return [AbsenceWriteThrottle()]
        return super().get_throttles()

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = AbsenceFilter
    search_fields = [
        "id_inscription__id_etudiant__nom",
        "id_inscription__id_etudiant__prenom",
    ]
    ordering_fields = ["id_absence", "duree_absence", "statut"]
    ordering = ["-id_absence"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update"):
            return [IsAdminOrSecretaryOrProfessor()]
        if self.action == "destroy":
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[AbsenceWriteSerializer], Type[AbsenceListSerializer]]:  # type: ignore[override]
        if self.action in ("create", "update", "partial_update"):
            return AbsenceWriteSerializer
        return AbsenceListSerializer

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return Absence.objects.none()
        qs = Absence.objects.select_related(
            "id_inscription__id_etudiant",
            "id_inscription__id_cours",
            "id_seance",
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt: Dict[str, Any] = {"id_inscription__id_etudiant": user}
            if active_year:
                flt["id_inscription__id_annee"] = active_year
            return qs.filter(**flt)
        if user.role == User.Role.PROFESSEUR:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt: Dict[str, Any] = {
                "id_inscription__id_cours__professeur": user,
                "id_inscription__status": Inscription.Status.EN_COURS,
            }
            if active_year:
                flt["id_inscription__id_annee"] = active_year
            return qs.filter(**flt)
        if user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
            return qs
        return qs.none()

    def perform_create(self, serializer):
        serializer.save(
            encodee_par=self.request.user,
            statut=Absence.Statut.NON_JUSTIFIEE,
        )
