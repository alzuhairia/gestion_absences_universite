"""
FICHIER : apps/api/views/course_viewset.py
RESPONSABILITE : ViewSet CRUD pour les cours.
  - Admin/Secretaire : acces complet
  - Professeur : lecture/detail sur ses propres cours
  - Etudiant : lecture des cours inscrits uniquement
"""
from typing import Type, Union, cast

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.enrollments.models import Inscription

from ..filters import CoursFilter
from ..pagination import StandardPagination
from ..permissions import IsAdminOrSecretary
from ..serializers import CoursDetailSerializer, CoursListSerializer, CoursWriteSerializer


@extend_schema_view(
    list=extend_schema(summary="List courses", tags=["Courses"]),
    retrieve=extend_schema(summary="Get course detail (with sessions & prerequisites)", tags=["Courses"]),
    create=extend_schema(summary="Create course", tags=["Courses"]),
    update=extend_schema(summary="Update course", tags=["Courses"]),
    partial_update=extend_schema(summary="Partial update course", tags=["Courses"]),
    destroy=extend_schema(summary="Delete course", tags=["Courses"]),
)
class CoursViewSet(viewsets.ModelViewSet):
    """
    CRUD for courses.

    - Admin/Secretary: full access
    - Professor: list/detail on own courses
    - Student: list/retrieve enrolled courses only
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CoursFilter
    search_fields = ["code_cours", "nom_cours"]
    ordering_fields = ["code_cours", "nom_cours", "niveau"]
    ordering = ["code_cours"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[CoursDetailSerializer], Type[CoursWriteSerializer], Type[CoursListSerializer]]:  # type: ignore[override]
        if self.action == "retrieve":
            return CoursDetailSerializer
        if self.action in ("create", "update", "partial_update"):
            return CoursWriteSerializer
        return CoursListSerializer

    def get_queryset(self):  # type: ignore[override]
        if getattr(self, "swagger_fake_view", False):
            return Cours.objects.none()
        qs = Cours.objects.select_related(
            "id_departement", "professeur", "id_annee"
        )
        if self.action == "retrieve":
            qs = qs.prefetch_related("seances", "prerequisites")
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            active_year = AnneeAcademique.objects.filter(active=True).first()
            ins_qs = Inscription.objects.filter(
                id_etudiant=user, status=Inscription.Status.EN_COURS
            )
            if active_year:
                ins_qs = ins_qs.filter(id_annee=active_year)
            enrolled_course_ids = ins_qs.values_list("id_cours", flat=True)
            return qs.filter(pk__in=enrolled_course_ids)
        if user.role == User.Role.PROFESSEUR:
            return qs.filter(professeur=user)
        return qs
