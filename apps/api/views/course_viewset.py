"""
Viewset des cours pour l'API REST UniAbsences.

``CoursViewSet`` fournit le CRUD sur le modèle ``Cours`` avec une portée de
queryset et de sérialiseur basée sur le rôle :

- Admin / Secrétaire : accès complet en lecture/écriture à tous les cours.
- Professeur : accès en lecture seule limité aux cours qu'il enseigne.
- Étudiant : accès en lecture seule limité aux cours auxquels il est
  activement inscrit (année académique en cours, statut EN_COURS).

L'action retrieve utilise ``CoursDetailSerializer`` qui précharge les
``seances`` et ``prerequisites`` liés pour une réponse enrichie ; list
utilise le ``CoursListSerializer`` plus léger.

Partie de l'API REST UniAbsences.
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
    CRUD pour les cours.

    - Admin/Secrétaire : accès complet
    - Professeur : list/detail sur ses propres cours
    - Étudiant : list/retrieve uniquement sur les cours inscrits
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = CoursFilter
    search_fields = ["code_cours", "nom_cours"]
    ordering_fields = ["code_cours", "nom_cours", "niveau"]
    ordering = ["code_cours"]

    def get_permissions(self):
        """
        Retourne les instances de permission qui contrôlent l'action courante.

        Matrice des permissions :
          - create / update / partial_update / destroy : admin ou secrétaire
            uniquement (les professeurs et étudiants ne doivent pas modifier
            les enregistrements de cours).
          - list / retrieve : tout utilisateur authentifié (le filtrage du
            queryset dans ``get_queryset`` applique l'isolation des données
            par rôle).

        Retourne :
            list : Une liste contenant une instance de permission.
        """
        # Les opérations d'écriture et de suppression sont restreintes aux rôles administratifs
        if self.action in ("create", "update", "partial_update", "destroy"):
            return [IsAdminOrSecretary()]
        # Actions de lecture : ouvertes à tous les rôles authentifiés ; filtrées par get_queryset
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[CoursDetailSerializer], Type[CoursWriteSerializer], Type[CoursListSerializer]]:  # type: ignore[override]
        """
        Retourne la classe de sérialiseur appropriée pour l'action courante.

        Sélection du sérialiseur :
          - retrieve : ``CoursDetailSerializer`` — inclut la liste imbriquée
            des séances et les cours prérequis pour une réponse enrichie sur
            un objet unique.
          - create / update / partial_update : ``CoursWriteSerializer`` —
            ensemble minimal de champs modifiables avec validation du niveau.
          - list (et toutes les autres actions) : ``CoursListSerializer`` —
            représentation plate, optimisée en lecture, avec des champs de
            noms dénormalisés.

        Retourne :
            Type : La classe de sérialiseur appropriée pour l'action courante.
        """
        # Vue détaillée : utilise le sérialiseur enrichi qui intègre séances et prérequis
        if self.action == "retrieve":
            return CoursDetailSerializer
        # Actions d'écriture : utilise le sérialiseur d'écriture avec validation
        if self.action in ("create", "update", "partial_update"):
            return CoursWriteSerializer
        # List (et toute autre action de lecture) : utilise le sérialiseur de liste léger
        return CoursListSerializer

    def get_queryset(self):  # type: ignore[override]
        """
        Retourne le queryset des cours filtré selon le rôle de l'utilisateur demandeur.

        Règles d'isolation des données :
          - ETUDIANT : uniquement les cours auxquels l'étudiant est activement
            inscrit (statut EN_COURS) dans l'année académique active courante.
          - PROFESSEUR : uniquement les cours assignés à ce professeur (toutes
            années).
          - ADMIN / SECRETAIRE : tous les cours sans filtrage.

        Pour l'action ``retrieve``, les séances liées (``seances``) et les
        cours prérequis (``prerequisites``) sont préchargés pour éviter des
        requêtes supplémentaires lorsque le sérialiseur de détail produit la
        réponse.

        Retourne :
            QuerySet[Cours] : Le queryset des cours filtré selon le rôle.
        """
        # Retourne un queryset vide lorsque drf-spectacular génère les aperçus de schéma
        if getattr(self, "swagger_fake_view", False):
            return Cours.objects.none()

        # Pré-jointure des clés étrangères partagées par toutes les variantes de sérialiseur
        qs = Cours.objects.select_related(
            "id_departement", "professeur", "id_annee"
        )

        # Préchargement des relations imbriquées uniquement lorsque le sérialiseur de détail les utilisera
        if self.action == "retrieve":
            qs = qs.prefetch_related("seances", "prerequisites")

        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            # Résolution de l'ensemble des PKs de cours auxquels l'étudiant est actuellement inscrit
            active_year = AnneeAcademique.objects.filter(active=True).first()
            ins_qs = Inscription.objects.filter(
                id_etudiant=user, status=Inscription.Status.EN_COURS
            )
            if active_year:
                ins_qs = ins_qs.filter(id_annee=active_year)
            enrolled_course_ids = ins_qs.values_list("id_cours", flat=True)
            return qs.filter(pk__in=enrolled_course_ids)

        if user.role == User.Role.PROFESSEUR:
            # Les professeurs voient uniquement les cours qu'ils sont assignés à enseigner
            return qs.filter(professeur=user)

        # Les admins et secrétaires voient tous les cours
        return qs
