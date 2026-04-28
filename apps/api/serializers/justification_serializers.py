"""
FICHIER : apps/api/serializers/justification_serializers.py
RESPONSABILITE : Serializers DRF pour les justificatifs d'absence.
"""
from rest_framework import serializers

from apps.absences.models import Absence, Justification
from apps.accounts.models import User


class JustificationListSerializer(serializers.ModelSerializer):
    absence_id = serializers.IntegerField(
        source="id_absence.id_absence", read_only=True
    )
    etudiant_name = serializers.CharField(
        source="id_absence.id_inscription.id_etudiant.get_full_name",
        read_only=True,
    )
    cours_code = serializers.CharField(
        source="id_absence.id_inscription.id_cours.code_cours",
        read_only=True,
    )
    validee_par_name = serializers.CharField(
        source="validee_par.get_full_name", read_only=True, default=None
    )

    class Meta:
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
    class Meta:
        model = Justification
        fields = ["id_absence", "document", "commentaire"]

    def validate_id_absence(self, value):
        request = self.context.get("request")
        if request and request.user.role == User.Role.ETUDIANT:
            if value.id_inscription.id_etudiant_id != request.user.pk:
                raise serializers.ValidationError(
                    "You can only justify your own absences."
                )

        if value.statut == Absence.Statut.JUSTIFIEE:
            raise serializers.ValidationError(
                "This absence is already justified."
            )
        if hasattr(value, "justification"):
            raise serializers.ValidationError(
                "A justification already exists for this absence."
            )
        return value


class JustificationProcessSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["approve", "reject"])
    commentaire_gestion = serializers.CharField(
        required=False, allow_blank=True, max_length=2000
    )
