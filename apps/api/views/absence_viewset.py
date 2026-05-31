"""
ViewSet d'absence pour l'API REST UniAbsences.

``AbsenceViewSet`` fournit un CRUD complet sur le modèle ``Absence`` avec un
filtrage du queryset et des permissions basé sur les rôles :

- Admin / Secrétaire : accès illimité à toutes les absences.
- Professeur : créer, mettre à jour et lister les absences limitées à ses
  propres cours et à l'année académique active.
- Étudiant : accès en lecture seule à ses propres absences dans l'année
  active.

Les opérations d'écriture (create, update, partial_update) sont en outre
limitées en débit par ``AbsenceWriteThrottle`` afin d'empêcher les
soumissions automatisées en masse.

Partie de l'API REST UniAbsences.
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
    CRUD pour les absences.

    - Admin/Secrétaire : accès complet
    - Professeur : créer/mettre à jour/lister pour ses cours
    - Étudiant : lecture seule pour ses propres absences
    """

    pagination_class = StandardPagination

    def get_throttles(self):
        """
        Renvoie les instances de throttle à appliquer à la requête courante.

        Les actions d'écriture (create, update, partial_update) sont limitées
        en débit par ``AbsenceWriteThrottle`` (scope : "absence_write") pour
        empêcher l'enregistrement automatisé d'absences en masse. Toutes les
        autres actions retombent sur la configuration de throttle globale
        définie dans les paramètres Django.

        Returns:
            list: Une liste contenant une instance ``AbsenceWriteThrottle``
                pour les actions d'écriture, ou la liste de throttles par
                défaut sinon.
        """
        # Import paresseux pour éviter un import circulaire au chargement du module
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
        """
        Renvoie les instances de permission qui encadrent l'action courante.

        Matrice des permissions :
          - create / update / partial_update : admin, secrétaire ou professeur
            (les professeurs doivent enregistrer les absences pour leurs
            propres cours).
          - destroy : admin ou secrétaire uniquement (les professeurs ne
            doivent pas supprimer d'enregistrements d'absences).
          - list / retrieve : tout utilisateur authentifié (le filtrage du
            queryset dans ``get_queryset`` impose l'isolation des données par
            rôle).

        Returns:
            list: Une liste contenant une instance de permission.
        """
        # Opérations d'écriture : professeurs inclus pour qu'ils puissent enregistrer des absences
        if self.action in ("create", "update", "partial_update"):
            return [IsAdminOrSecretaryOrProfessor()]
        # La suppression est restreinte aux rôles administratifs uniquement
        if self.action == "destroy":
            return [IsAdminOrSecretary()]
        # Actions de lecture : ouvertes à tous les rôles authentifiés ; filtré par get_queryset
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[AbsenceWriteSerializer], Type[AbsenceListSerializer]]:  # type: ignore[override]
        """
        Renvoie la classe de sérialiseur appropriée pour l'action courante.

        Les actions d'écriture utilisent ``AbsenceWriteSerializer`` qui
        applique la validation des règles métier (contraintes de type, limites
        de durée). Toutes les actions de lecture utilisent
        ``AbsenceListSerializer`` qui inclut des champs dénormalisés pour le
        nom de l'étudiant, le code du cours et les bornes horaires de la
        séance.

        Returns:
            Type: ``AbsenceWriteSerializer`` pour les actions
                create/update, ou ``AbsenceListSerializer`` pour les actions
                list/retrieve.
        """
        # Chemin d'écriture : utiliser le sérialiseur d'écriture validant
        if self.action in ("create", "update", "partial_update"):
            return AbsenceWriteSerializer
        # Chemin de lecture : utiliser le sérialiseur de liste enrichi avec champs dénormalisés
        return AbsenceListSerializer

    def get_queryset(self):  # type: ignore[override]
        """
        Renvoie le queryset d'absences filtré selon le rôle de l'utilisateur
        faisant la requête.

        Règles d'isolation des données :
          - ETUDIANT : absences pour les propres inscriptions de l'étudiant
            dans l'année académique actuellement active.
          - PROFESSEUR : absences pour toutes les inscriptions des cours
            enseignés par ce professeur, limitées aux inscriptions actives et
            à l'année active.
          - ADMIN / SECRETAIRE : tous les enregistrements d'absences (aucun
            filtrage).
          - Tout autre rôle : queryset vide (refus par défaut).

        Un appel ``select_related`` est appliqué en amont pour éviter les
        requêtes N+1 lorsque le sérialiseur lit le nom de l'étudiant, le code
        du cours ou les données de séance.

        Returns:
            QuerySet[Absence]: Le queryset d'absences filtré par rôle.
        """
        # Renvoie un queryset vide lorsque drf-spectacular génère des aperçus de schéma
        if getattr(self, "swagger_fake_view", False):
            return Absence.objects.none()

        # Pré-jointure des lignes liées pour éliminer les requêtes N+1 dans le sérialiseur
        qs = Absence.objects.select_related(
            "id_inscription__id_etudiant",
            "id_inscription__id_cours",
            "id_seance",
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            # Les étudiants ne voient que leurs propres absences ; filtré sur l'année active si disponible
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt: Dict[str, Any] = {"id_inscription__id_etudiant": user}
            if active_year:
                flt["id_inscription__id_annee"] = active_year
            return qs.filter(**flt)

        if user.role == User.Role.PROFESSEUR:
            # Les professeurs voient les absences de leurs cours ; inscriptions actives dans l'année active uniquement
            active_year = AnneeAcademique.objects.filter(active=True).first()
            flt: Dict[str, Any] = {
                "id_inscription__id_cours__professeur": user,
                "id_inscription__status": Inscription.Status.EN_COURS,
            }
            if active_year:
                flt["id_inscription__id_annee"] = active_year
            return qs.filter(**flt)

        # Les admins et secrétaires ont un accès illimité
        if user.role in (User.Role.ADMIN, User.Role.SECRETAIRE):
            return qs

        # Refus par défaut pour tout rôle inconnu ou inattendu
        return qs.none()

    def perform_create(self, serializer):
        """
        Enregistre un nouvel enregistrement d'absence avec les champs définis
        par le système.

        Deux champs sont injectés automatiquement au moment de la création
        plutôt que d'être acceptés depuis le client :
          - ``encodee_par`` : l'utilisateur actuellement authentifié
            (professeur ou admin/secrétaire qui enregistre l'absence).
          - ``statut`` : commence toujours par ``NON_JUSTIFIEE`` ; les
            transitions de statut sont pilotées par le workflow de
            justification, pas par une entrée directe.

        Parameters:
            serializer (AbsenceWriteSerializer): L'instance de sérialiseur
                validée prête à être sauvegardée.
        """
        # Enregistrer qui a saisi cette absence ; le statut initial est toujours non justifié
        serializer.save(
            encodee_par=self.request.user,
            statut=Absence.Statut.NON_JUSTIFIEE,
        )
