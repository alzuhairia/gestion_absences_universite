"""
FICHIER : apps/api/serializers/user_serializers.py
RESPONSABILITE : Serializers DRF pour les utilisateurs et etudiants.
"""
from rest_framework import serializers

from apps.accounts.models import User


class UserListSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id_utilisateur",
            "nom",
            "prenom",
            "email",
            "role",
            "actif",
            "niveau",
            "full_name",
            "date_creation",
        ]
        read_only_fields = fields


class StudentSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(source="get_full_name", read_only=True)

    class Meta:
        model = User
        fields = [
            "id_utilisateur",
            "nom",
            "prenom",
            "email",
            "niveau",
            "actif",
            "full_name",
            "date_creation",
        ]
        read_only_fields = ["id_utilisateur", "date_creation", "full_name"]
        extra_kwargs = {
            "email": {"required": True},
            "nom": {"required": True},
            "prenom": {"required": True},
            "niveau": {"required": True},
        }

    def validate_niveau(self, value):
        if value not in (1, 2, 3):
            raise serializers.ValidationError("Niveau must be 1, 2, or 3.")
        return value
