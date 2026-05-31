"""
Viewset des inscriptions pour l'API REST UniAbsences.

``InscriptionViewSet`` fournit le CRUD sur le modèle ``Inscription`` avec
une portée de queryset basée sur le rôle :

- Admin / Secrétaire : accès complet en lecture/écriture à toutes les inscriptions.
- Professeur : accès en lecture seule limité aux inscriptions dans ses cours
  (statut EN_COURS, année académique active).
- Étudiant : accès en lecture seule limité à ses propres inscriptions actives
  (statut EN_COURS, année académique active).

Partie de l'API REST UniAbsences.
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
    CRUD pour les inscriptions.

    - Admin/Secrétaire : accès complet
    - Professeur : lecture seule pour ses cours
    - Étudiant : lecture seule pour ses propres inscriptions
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
        """
        Retourne les instances de permission qui contrôlent l'action courante.

        Matrice des permissions :
          - create / update / partial_update / destroy : admin ou secrétaire
            uniquement (les professeurs et étudiants ne doivent pas créer ou
            modifier les enregistrements d'inscription).
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

    def get_serializer_class(self) -> Union[Type[InscriptionWriteSerializer], Type[InscriptionListSerializer]]:  # type: ignore[override]
        """
        Retourne la classe de sérialiseur appropriée pour l'action courante.

        Les actions d'écriture utilisent ``InscriptionWriteSerializer`` qui
        applique la validation du rôle étudiant sur ``id_etudiant``. Toutes
        les actions de lecture utilisent ``InscriptionListSerializer`` qui
        inclut des champs dénormalisés de nom d'étudiant et de cours pour
        réduire les recherches côté client.

        Retourne :
            Type : ``InscriptionWriteSerializer`` pour les actions create/update,
                ou ``InscriptionListSerializer`` pour les actions list/retrieve.
        """
        # Chemin d'écriture : utilise le sérialiseur d'écriture avec validation
        if self.action in ("create", "update", "partial_update"):
            return InscriptionWriteSerializer
        # Chemin de lecture : utilise le sérialiseur de liste enrichi avec champs dénormalisés
        return InscriptionListSerializer

    def get_queryset(self):  # type: ignore[override]
        """
        Retourne le queryset des inscriptions filtré selon le rôle de l'utilisateur demandeur.

        Règles d'isolation des données :
          - ETUDIANT : uniquement les propres inscriptions actives de
            l'étudiant (statut EN_COURS) dans l'année académique active
            courante.
          - PROFESSEUR : uniquement les inscriptions actives dans les cours
            enseignés par ce professeur, restreintes à l'année académique
            active.
          - ADMIN / SECRETAIRE : toutes les inscriptions sans filtrage.

        Un appel ``select_related`` est appliqué en amont pour éviter les
        requêtes N+1 lorsque le sérialiseur de liste produit les champs de
        nom d'étudiant et de cours.

        Retourne :
            QuerySet[Inscription] : Le queryset des inscriptions filtré selon le rôle.
        """
        # Retourne un queryset vide lorsque drf-spectacular génère les aperçus de schéma
        if getattr(self, "swagger_fake_view", False):
            return Inscription.objects.none()

        # Pré-jointure des lignes liées pour éliminer les requêtes N+1 dans le sérialiseur
        qs = Inscription.objects.select_related(
            "id_etudiant", "id_cours", "id_annee"
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            # Les étudiants voient uniquement leurs propres inscriptions actuellement actives
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt = {"id_etudiant": user, "status": Inscription.Status.EN_COURS}
            if active_year:
                flt["id_annee"] = active_year
            return qs.filter(**flt)

        if user.role == User.Role.PROFESSEUR:
            # Les professeurs voient les inscriptions actives dans leurs propres cours pour l'année active
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt = {"id_cours__professeur": user, "status": Inscription.Status.EN_COURS}
            if active_year:
                flt["id_annee"] = active_year
            return qs.filter(**flt)

        # Les admins et secrétaires voient toutes les inscriptions
        return qs
