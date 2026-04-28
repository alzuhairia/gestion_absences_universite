"""
FICHIER : apps/api/serializers/enrollment_serializers.py
RESPONSABILITE : Serializers DRF pour les inscriptions.
"""
from rest_framework import serializers

from apps.accounts.models import User
from apps.enrollments.models import Inscription


class InscriptionListSerializer(serializers.ModelSerializer):
    etudiant_name = serializers.CharField(
        source="id_etudiant.get_full_name", read_only=True
    )
    cours_code = serializers.CharField(
        source="id_cours.code_cours", read_only=True
    )
    cours_name = serializers.CharField(
        source="id_cours.nom_cours", read_only=True
    )
    annee = serializers.CharField(source="id_annee.libelle", read_only=True)

    class Meta:
        model = Inscription
        fields = [
            "id_inscription",
            "id_etudiant",
            "etudiant_name",
            "id_cours",
            "cours_code",
            "cours_name",
            "id_annee",
            "annee",
            "type_inscription",
            "eligible_examen",
            "status",
            "exemption_40",
            "motif_exemption",
        ]


class InscriptionWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Inscription
        fields = [
            "id_etudiant",
            "id_cours",
            "id_annee",
            "type_inscription",
        ]

    def validate_id_etudiant(self, value):
        if value.role != User.Role.ETUDIANT:
            raise serializers.ValidationError("User must have role ETUDIANT.")
        return value
