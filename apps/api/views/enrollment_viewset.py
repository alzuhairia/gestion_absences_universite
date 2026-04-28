"""
FICHIER : apps/api/views/enrollment_viewset.py
RESPONSABILITE : ViewSet CRUD pour les inscriptions.
  - Admin/Secretaire : acces complet
  - Professeur : lecture seule (cours actifs)
  - Etudiant : lecture de ses propres inscriptions actives
"""
from typing import Type, Union, cast

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from apps.academic_sessions.models import AnneeAcademique
from apps.accounts.models import User
from apps.enrollments.models import Inscription

from ..filters import InscriptionFilter
from ..pagination import StandardPagination
from ..permissions import IsAdminOrSecretary
from ..serializers import InscriptionListSerializer, InscriptionWriteSerializer


@extend_schema_view(
    list=extend_schema(summary="List enrollments", tags=["Enrollments"]),
    retrieve=extend_schema(summary="Get enrollment detail", tags=["Enrollments"]),
    create=extend_schema(summary="Create enrollment", tags=["Enrollments"]),
    update=extend_schema(summary="Update enrollment", tags=["Enrollments"]),
    partial_update=extend_schema(summary="Partial update enrollment", tags=["Enrollments"]),
    destroy=extend_schema(summary="Delete enrollment", tags=["Enrollments"]),
)
class InscriptionViewSet(viewsets.ModelViewSet):
    """
    CRUD for enrollments.

    - Admin/Secretary: full access
    - Professor: read-only for their courses
    - Student: read-only for own enrollments
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = InscriptionFilter
    search_fields = [
        "id_etudiant__nom",
        "id_etudiant__prenom",
        "id_cours__code_cours",
    ]
    ordering_fields = ["id_inscription", "status", "type_inscription"]
    ordering = ["-id_inscription"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[InscriptionWriteSerializer], Type[InscriptionListSerializer]]:  # type: ignore[override]
        if self.action in ("create", "update", "partial_update"):
            return InscriptionWriteSerializer
        return InscriptionListSerializer

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return Inscription.objects.none()
        qs = Inscription.objects.select_related(
            "id_etudiant", "id_cours", "id_annee"
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt = {"id_etudiant": user, "status": Inscription.Status.EN_COURS}
            if active_year:
                flt["id_annee"] = active_year
            return qs.filter(**flt)
        if user.role == User.Role.PROFESSEUR:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt = {"id_cours__professeur": user, "status": Inscription.Status.EN_COURS}
            if active_year:
                flt["id_annee"] = active_year
            return qs.filter(**flt)
        return qs
