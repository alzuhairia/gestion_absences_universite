"""
FICHIER : apps/api/views/student_viewset.py
RESPONSABILITE : ViewSet CRUD pour les etudiants.
  - Admin/Secretaire : acces complet
  - Professeur : lecture seule (etudiants de ses cours)
  - Etudiant : lecture de son propre profil uniquement
"""
from typing import Type, Union

from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import viewsets
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.permissions import IsAuthenticated

from apps.accounts.models import User
from apps.enrollments.models import Inscription

from ..filters import StudentFilter
from ..pagination import StandardPagination
from ..permissions import IsAdminOrSecretary
from ..serializers import StudentSerializer, UserListSerializer


@extend_schema_view(
    list=extend_schema(summary="List students", tags=["Students"]),
    retrieve=extend_schema(summary="Get student detail", tags=["Students"]),
    create=extend_schema(summary="Create student", tags=["Students"]),
    update=extend_schema(summary="Update student", tags=["Students"]),
    partial_update=extend_schema(summary="Partial update student", tags=["Students"]),
    destroy=extend_schema(summary="Deactivate student (soft delete)", tags=["Students"]),
)
class StudentViewSet(viewsets.ModelViewSet):
    """
    CRUD for student users.

    - Admin/Secretary: full access
    - Professor: list/retrieve only (students in their courses)
    - Student: retrieve own profile only
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = StudentFilter
    search_fields = ["nom", "prenom", "email"]
    ordering_fields = ["nom", "prenom", "email", "niveau", "date_creation"]
    ordering = ["nom", "prenom"]

    def get_permissions(self):
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[UserListSerializer], Type[StudentSerializer]]:  # type: ignore[override]
        if self.action == "list":
            return UserListSerializer
        return StudentSerializer

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return User.objects.none()
        qs = User.objects.filter(role=User.Role.ETUDIANT)
        user = self.request.user

        if user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
            return qs
        if user.role == User.Role.PROFESSEUR:
            student_ids = Inscription.objects.filter(
                id_cours__professeur=user,
                status=Inscription.Status.EN_COURS,
            ).values_list("id_etudiant", flat=True)
            return qs.filter(pk__in=student_ids)
        if user.role == User.Role.ETUDIANT:
            return qs.filter(pk=user.pk)
        return qs.none()

    def perform_create(self, serializer):
        user = serializer.save(role=User.Role.ETUDIANT)
        user.set_password(User.objects.make_random_password())
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])

    def perform_destroy(self, instance):
        instance.actif = False
        instance.save(update_fields=["actif"])
