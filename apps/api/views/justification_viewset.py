"""
Viewset des justifications pour l'API REST UniAbsences.

``JustificationViewSet`` gère le flux de justification des absences avec
un contrôle d'accès spécifique au rôle :

- Étudiant : soumet un nouveau document de justification (POST
  /justifications/) et liste ses propres soumissions. Limité en débit par
  ``JustificationUploadThrottle``.
- Admin / Secrétaire : liste toutes les justifications et les approuve ou
  les rejette via l'action personnalisée ``process`` (POST
  /justifications/{id}/process/).
- Professeur : accès en lecture seule limité aux justifications pour ses cours.

L'action ``process`` pilote la machine à états sur l'enregistrement
``Justification`` (EN_ATTENTE → ACCEPTEE ou REFUSEE) et envoie des
notifications par email à la fois à l'étudiant et au professeur du cours.

Partie de l'API REST UniAbsences.
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
    Gestion des justifications.

    - Étudiant : crée des justifications pour ses propres absences, liste les siennes
    - Admin/Secrétaire : liste toutes, approuve/rejette via l'action process
    - Professeur : lecture seule pour ses cours
    """

    pagination_class = StandardPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = JustificationFilter
    ordering_fields = ["date_soumission", "state"]
    ordering = ["-date_soumission"]

    def get_throttles(self):
        """
        Retourne les instances de throttle à appliquer à la requête courante.

        L'action ``create`` (soumission de document par l'étudiant) est
        limitée en débit par ``JustificationUploadThrottle`` (scope :
        "justification_upload") pour empêcher le spam d'upload de documents.
        Toutes les autres actions retombent sur la configuration globale
        de throttle définie dans les paramètres Django.

        Retourne :
            list : Une liste contenant une instance de
                ``JustificationUploadThrottle`` pour create, ou la liste de
                throttle par défaut sinon.
        """
        # Import paresseux pour éviter un import circulaire au chargement du module
        if self.action == "create":
            from apps.api.throttles import JustificationUploadThrottle
            return [JustificationUploadThrottle()]
        return super().get_throttles()

    def get_permissions(self):
        """
        Retourne les instances de permission qui contrôlent l'action courante.

        Matrice des permissions :
          - create : rôle ETUDIANT uniquement — les étudiants soumettent
            leurs propres documents de justification.
          - process : admin ou secrétaire uniquement — le personnel approuve
            ou rejette les justifications en attente.
          - list / retrieve : tout utilisateur authentifié (le filtrage du
            queryset dans ``get_queryset`` applique l'isolation des données
            par rôle).

        Retourne :
            list : Une liste contenant une instance de permission.
        """
        # Seuls les étudiants peuvent soumettre des justifications
        if self.action == "create":
            return [IsStudent()]
        # Seuls les admin/secrétaire peuvent approuver ou rejeter les justifications
        if self.action == "process":
            return [IsAdminOrSecretary()]
        # Actions de lecture : ouvertes à tous les rôles authentifiés ; filtrées par get_queryset
        return [IsAuthenticated()]

    def get_serializer_class(self) -> Union[Type[JustificationCreateSerializer], Type[JustificationProcessSerializer], Type[JustificationListSerializer]]:  # type: ignore[override]
        """
        Retourne la classe de sérialiseur appropriée pour l'action courante.

        Sélection du sérialiseur :
          - create : ``JustificationCreateSerializer`` — applique les règles
            de propriété et de non-duplication avant de sauvegarder le
            document.
          - process : ``JustificationProcessSerializer`` — valide le choix
            d'action approuver/rejeter et le commentaire de gestion
            facultatif.
          - list / retrieve : ``JustificationListSerializer`` — vue en
            lecture seule avec champs dénormalisés d'étudiant et de cours.

        Retourne :
            Type : La classe de sérialiseur appropriée pour l'action courante.
        """
        # Chemin de soumission étudiant : valide la propriété et l'état de l'absence
        if self.action == "create":
            return JustificationCreateSerializer
        # Chemin d'approbation/rejet du personnel : valide le choix d'action et le commentaire
        if self.action == "process":
            return JustificationProcessSerializer
        # Chemin de lecture : vue liste enrichie avec champs dénormalisés
        return JustificationListSerializer

    def get_queryset(self):  # type: ignore[override]
        """
        Retourne le queryset des justifications filtré selon le rôle de l'utilisateur demandeur.

        Règles d'isolation des données :
          - ETUDIANT : uniquement les justifications soumises par cet
            étudiant (traverse Justification → Absence → Inscription →
            Étudiant).
          - PROFESSEUR : uniquement les justifications pour les absences
            dans les cours enseignés par ce professeur (traverse
            Justification → Absence → Inscription → Cours → Professeur).
          - ADMIN / SECRETAIRE : toutes les justifications sans filtrage.

        Un appel ``select_related`` profond est appliqué en amont pour
        éviter les requêtes N+1 lorsque le sérialiseur de liste produit
        les champs de nom d'étudiant, code de cours et nom de validateur.

        Retourne :
            QuerySet[Justification] : Le queryset des justifications filtré selon le rôle.
        """
        # Retourne un queryset vide lorsque drf-spectacular génère les aperçus de schéma
        if getattr(self, "swagger_fake_view", False):
            return Justification.objects.none()

        # Pré-jointure de la chaîne complète nécessaire au sérialiseur de liste pour éviter les requêtes N+1
        qs = Justification.objects.select_related(
            "id_absence__id_inscription__id_etudiant",
            "id_absence__id_inscription__id_cours",
            "validee_par",
        )
        user = cast(User, self.request.user)

        if user.role == User.Role.ETUDIANT:
            # Les étudiants voient uniquement les justifications pour leurs propres absences
            return qs.filter(
                id_absence__id_inscription__id_etudiant=user
            )
        if user.role == User.Role.PROFESSEUR:
            # Les professeurs voient les justifications pour les absences dans leurs cours
            return qs.filter(
                id_absence__id_inscription__id_cours__professeur=user
            )

        # Les admins et secrétaires voient toutes les justifications
        return qs

    def perform_create(self, serializer):
        """
        Persiste une nouvelle justification et transitionne le statut de l'absence liée.

        Deux opérations sont effectuées dans une seule transaction de base
        de données pour garantir la cohérence :
          1. Sauvegarder le nouvel enregistrement ``Justification``.
          2. Mettre à jour le statut de l'``Absence`` liée de ``NON_JUSTIFIEE``
             à ``EN_ATTENTE`` (en attente de révision).

        Après la validation de la transaction, une notification par email
        est envoyée au professeur du cours (si un est assigné) pour
        l'informer qu'un étudiant a soumis un document de justification.
        La livraison de l'email est intentionnellement effectuée en dehors
        de la transaction afin qu'une défaillance du serveur de messagerie
        ne provoque pas le rollback de l'enregistrement de justification.

        Paramètres :
            serializer (JustificationCreateSerializer) : L'instance de
                sérialiseur validée prête à être sauvegardée.
        """
        # Sauvegarde atomiquement la justification et met à jour le statut de l'absence ensemble
        with transaction.atomic():
            justification = serializer.save()
            # Verrouille la ligne d'absence pour empêcher les mises à jour de statut concurrentes
            absence = Absence.objects.select_for_update().get(
                pk=justification.id_absence_id
            )
            # Transitionne l'absence vers "en attente de révision" maintenant qu'un document a été soumis
            absence.statut = Absence.Statut.EN_ATTENTE
            absence.save(update_fields=["statut"])

        # Notifie le professeur du cours en dehors de la transaction (l'échec de l'email ne doit pas
        # provoquer le rollback de la justification ou de la mise à jour du statut de l'absence)
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
        """
        Approuve ou rejette un document de justification en attente.

        Cette action pilote la machine à états de la justification :
          - ``approve`` → ``Justification.state`` = ACCEPTEE,
                           ``Absence.statut``      = JUSTIFIEE.
          - ``reject``  → ``Justification.state`` = REFUSEE,
                           ``Absence.statut``      = NON_JUSTIFIEE (réinitialisée).

        La transition d'état est protégée par une vérification
        d'idempotence : si la justification n'est pas actuellement dans
        l'état ``EN_ATTENTE`` (c'est-à-dire qu'elle a déjà été traitée),
        l'endpoint retourne HTTP 400.

        Les lignes de justification et d'absence sont verrouillées avec
        ``SELECT FOR UPDATE`` dans une transaction de base de données pour
        empêcher les conditions de concurrence lorsque deux membres du
        personnel traitent la même justification simultanément.

        Après la validation de la transaction, des notifications par email
        sont envoyées à l'étudiant (notification de décision) et au
        professeur (si un est assigné). La livraison de l'email est
        effectuée en dehors de la transaction afin qu'une défaillance du
        serveur de messagerie ne provoque pas le rollback du changement
        d'état.

        Paramètres :
            request (Request) : La requête authentifiée admin ou secrétaire.
                Corps attendu : ``{"action": "approve"|"reject",
                "commentaire_gestion": "<commentaire facultatif>"}``
            pk (int | None) : Clé primaire de la ``Justification`` à traiter.

        Retourne :
            Response (HTTP 200) : La justification mise à jour sérialisée
                comme ``JustificationListSerializer``.
            Response (HTTP 400) : Si la justification a déjà été traitée
                ou si les données de la requête sont invalides.
        """
        # Valide le choix d'action entrant et le commentaire facultatif
        serializer = JustificationProcessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = cast(Dict[str, Any], serializer.validated_data)
        action_value = validated_data["action"]
        comment = validated_data.get("commentaire_gestion", "")

        with transaction.atomic():
            # Verrouille les deux lignes pour empêcher le traitement concurrent par deux membres du personnel
            justification = Justification.objects.select_for_update().get(
                pk=self.get_object().pk
            )
            absence = Absence.objects.select_for_update().get(
                pk=justification.id_absence_id
            )

            # Protection d'idempotence : rejette les requêtes pour les justifications déjà traitées
            if justification.state != Justification.State.EN_ATTENTE:
                return Response(
                    {"detail": "This justification has already been processed."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Applique la transition de machine à états en fonction de l'action demandée
            if action_value == "approve":
                justification.state = Justification.State.ACCEPTEE
                absence.statut = Absence.Statut.JUSTIFIEE
            else:
                # Le rejet réinitialise l'absence à son état non justifié d'origine
                justification.state = Justification.State.REFUSEE
                absence.statut = Absence.Statut.NON_JUSTIFIEE

            # Enregistre le membre du personnel qui a traité cette justification et quand
            justification.validee_par = request.user
            justification.date_validation = timezone.now()
            justification.commentaire_gestion = comment
            justification.save()
            absence.save(update_fields=["statut"])

        # --- Notifications par email (en dehors de la transaction pour isoler les échecs de mail) ---
        student = absence.id_inscription.id_etudiant
        course_code = absence.id_seance.id_cours.code_cours
        date_str = str(absence.id_seance.date_seance)
        approved = action_value == "approve"

        # Notifie l'étudiant de la décision
        subj, body, html_body = build_justification_decision_email(
            student, course_code, date_str, approved, comment
        )
        send_notification_email(student, subj, body, html_body=html_body)

        # Notifie le professeur du cours si un est assigné
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
