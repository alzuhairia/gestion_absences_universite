"""
Sérialiseurs de justification pour l'API REST UniAbsences.

Ce module fournit trois sérialiseurs pour la ressource ``Justification``
(document d'absence) :

- ``JustificationListSerializer`` — représentation en lecture seule utilisée
  par les points de terminaison de liste et de récupération ; parcourt la
  relation Absence → Inscription → User pour faire ressortir le nom de
  l'étudiant et le code du cours sans requêtes supplémentaires.

- ``JustificationCreateSerializer`` — sérialiseur d'écriture pour la
  soumission par l'étudiant ; applique deux règles métier : les étudiants ne
  peuvent justifier que leurs propres absences, et une justification ne peut
  être soumise pour une absence déjà acceptée ou disposant déjà d'un document
  en attente.

- ``JustificationProcessSerializer`` — sérialiseur sans modèle utilisé par le
  point de terminaison d'approbation par le secrétariat ; accepte un choix
  ``action`` (approve / reject) et un commentaire de gestion optionnel.

Partie de l'API REST UniAbsences.
"""
from rest_framework import serializers

from apps.absences.models import Absence, Justification
from apps.accounts.models import User


class JustificationListSerializer(serializers.ModelSerializer):
    """
    Vue plate en lecture seule d'un enregistrement de justification.

    Parcourt la chaîne Absence → Inscription → User pour inclure le nom
    complet de l'étudiant et le code du cours, réduisant le nombre
    d'allers-retours nécessaires aux consommateurs de vues de liste.
    """

    # ID d'absence explicite — évite d'imbriquer un objet d'absence complet
    absence_id = serializers.IntegerField(
        source="id_absence.id_absence", read_only=True
    )
    # Parcours profond : Justification → Absence → Inscription → Étudiant
    etudiant_name = serializers.CharField(
        source="id_absence.id_inscription.id_etudiant.get_full_name",
        read_only=True,
    )
    # Parcours profond : Justification → Absence → Inscription → Cours
    cours_code = serializers.CharField(
        source="id_absence.id_inscription.id_cours.code_cours",
        read_only=True,
    )
    # Nom du membre du personnel ayant approuvé/rejeté ; None si non encore traité
    validee_par_name = serializers.CharField(
        source="validee_par.get_full_name", read_only=True, default=None
    )

    class Meta:
        """Configuration DRF : modèle ``Justification`` et champs dénormalisés exposés en lecture."""

        model = Justification
        fields = [
            "id_justification",
            "absence_id",
            "etudiant_name",
            "cours_code",
            "document",
            "commentaire",
            "commentaire_gestion",
            "date_soumission",
            "state",
            "validee_par",
            "validee_par_name",
            "date_validation",
        ]


class JustificationCreateSerializer(serializers.ModelSerializer):
    """
    Sérialiseur d'écriture pour la soumission d'une justification par
    l'étudiant.

    Règles métier appliquées dans ``validate_id_absence`` :
    - Un étudiant ne peut soumettre une justification que pour sa propre
      absence (vérifié via ``id_inscription.id_etudiant_id``).
    - L'absence cible ne doit pas déjà être JUSTIFIEE.
    - L'absence cible ne doit pas déjà être liée à un document de
      justification.
    """

    class Meta:
        """Configuration DRF : modèle ``Justification`` et champs acceptés à la soumission étudiante."""

        model = Justification
        fields = ["id_absence", "document", "commentaire"]

    def validate_id_absence(self, value):
        """
        Vérifie qu'un étudiant peut soumettre une justification pour cette
        absence.

        Trois règles sont appliquées dans l'ordre :

        1. Vérification de propriété — si l'utilisateur faisant la requête est
           un étudiant, l'absence doit appartenir à sa propre inscription. Les
           utilisateurs du personnel contournent cette vérification et peuvent
           soumettre au nom de tout étudiant.
        2. Vérification du statut — l'absence ne doit pas déjà être dans
           l'état JUSTIFIEE (c'est-à-dire qu'une justification précédente a
           déjà été acceptée).
        3. Vérification de doublon — l'absence ne doit pas déjà être liée à
           un objet ``Justification``, empêchant la double soumission.

        Parameters:
            value (Absence): L'instance ``Absence`` résolue à partir de la
                clé primaire entrante.

        Returns:
            Absence: L'instance d'absence validée, inchangée.

        Raises:
            serializers.ValidationError: Si l'une des trois règles est
                violée.
        """
        request = self.context.get("request")

        # Règle 1 : les étudiants ne peuvent justifier que leurs propres absences
        if request and request.user.role == User.Role.ETUDIANT:
            if value.id_inscription.id_etudiant_id != request.user.pk:
                raise serializers.ValidationError(
                    "Vous ne pouvez justifier que vos propres absences."
                )

        # Règle 2 : rejeter si l'absence est déjà dans un état entièrement justifié
        if value.statut == Absence.Statut.JUSTIFIEE:
            raise serializers.ValidationError(
                "Cette absence est déjà justifiée."
            )

        # Règle 3 : rejeter si un document de justification existe déjà (garde un-à-un)
        if hasattr(value, "justification"):
            raise serializers.ValidationError(
                "Une justification existe déjà pour cette absence."
            )
        return value


class JustificationProcessSerializer(serializers.Serializer):
    """
    Sérialiseur sans modèle pour le point de terminaison d'approbation /
    rejet par le secrétariat.

    Le champ ``action`` déclenche la transition de la machine d'états sur
    l'enregistrement ``Justification``. ``commentaire_gestion`` est optionnel
    mais recommandé lors d'un rejet, car il est affiché à l'étudiant.
    """

    action = serializers.ChoiceField(choices=["approve", "reject"])
    commentaire_gestion = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )
