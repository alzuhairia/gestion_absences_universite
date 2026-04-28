"""
FICHIER : apps/api/serializers/course_serializers.py
RESPONSABILITE : Serializers DRF pour les seances et les cours.
"""
from rest_framework import serializers

from apps.academic_sessions.models import Seance
from apps.academics.models import Cours


class SeanceSerializer(serializers.ModelSerializer):
    cours_code = serializers.CharField(
        source="id_cours.code_cours", read_only=True
    )
    duree = serializers.FloatField(source="duree_heures", read_only=True)

    class Meta:
        model = Seance
        fields = [
            "id_seance",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "id_cours",
            "cours_code",
            "id_annee",
            "validated",
            "duree",
        ]
        read_only_fields = [
            "id_seance",
            "validated",
            "cours_code",
            "duree",
        ]


class CoursListSerializer(serializers.ModelSerializer):
    departement_name = serializers.CharField(
        source="id_departement.nom_departement", read_only=True
    )
    professeur_name = serializers.CharField(
        source="professeur.get_full_name", read_only=True, default=None
    )
    annee = serializers.CharField(source="id_annee.libelle", read_only=True)
    seuil_effectif = serializers.IntegerField(
        source="get_seuil_absence", read_only=True
    )

    class Meta:
        model = Cours
        fields = [
            "id_cours",
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",
            "seuil_effectif",
            "id_departement",
            "departement_name",
            "professeur",
            "professeur_name",
            "id_annee",
            "annee",
            "niveau",
            "actif",
        ]


class CoursDetailSerializer(CoursListSerializer):
    seances = SeanceSerializer(many=True, read_only=True)
    prerequisites = CoursListSerializer(many=True, read_only=True)

    class Meta(CoursListSerializer.Meta):
        fields = CoursListSerializer.Meta.fields + ["seances", "prerequisites"]


class CoursWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cours
        fields = [
            "code_cours",
            "nom_cours",
            "nombre_total_periodes",
            "seuil_absence",
            "id_departement",
            "professeur",
            "id_annee",
            "niveau",
            "prerequisites",
            "actif",
        ]

    def validate_niveau(self, value):
        if value not in (1, 2, 3):
            raise serializers.ValidationError("Niveau must be 1, 2, or 3.")
        return value
