"""
FICHIER : apps/api/serializers/absence_serializers.py
RESPONSABILITE : Serializers DRF pour les absences.
"""
from rest_framework import serializers

from apps.absences.models import Absence


class AbsenceListSerializer(serializers.ModelSerializer):
    etudiant_name = serializers.CharField(
        source="id_inscription.id_etudiant.get_full_name", read_only=True
    )
    cours_code = serializers.CharField(
        source="id_inscription.id_cours.code_cours", read_only=True
    )
    date_seance = serializers.DateField(
        source="id_seance.date_seance", read_only=True
    )
    heure_debut = serializers.TimeField(
        source="id_seance.heure_debut", read_only=True
    )
    heure_fin = serializers.TimeField(
        source="id_seance.heure_fin", read_only=True
    )

    class Meta:
        model = Absence
        fields = [
            "id_absence",
            "id_inscription",
            "etudiant_name",
            "cours_code",
            "id_seance",
            "date_seance",
            "heure_debut",
            "heure_fin",
            "type_absence",
            "duree_absence",
            "statut",
            "note_professeur",
            "encodee_par",
        ]


class AbsenceWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Absence
        fields = [
            "id_inscription",
            "id_seance",
            "type_absence",
            "duree_absence",
            "note_professeur",
        ]

    def validate_type_absence(self, value):
        allowed = (Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL)
        if value not in allowed:
            raise serializers.ValidationError(
                f"Type invalide. Valeurs autorisées : {', '.join(allowed)}"
            )
        return value

    def validate(self, data):
        type_absence = data.get("type_absence")
        duree = data.get("duree_absence")
        if type_absence == Absence.TypeAbsence.PARTIEL and (not duree or duree <= 0):
            raise serializers.ValidationError(
                {"duree_absence": "La durée est obligatoire pour une absence partielle."}
            )

        seance = data.get("id_seance")
        if seance and duree is not None and duree > 0:
            duree_seance = seance.duree_heures() if hasattr(seance, "duree_heures") else None
            if duree_seance and float(duree) > duree_seance:
                raise serializers.ValidationError(
                    {"duree_absence": f"La durée ({duree}h) ne peut pas dépasser la durée de la séance ({duree_seance}h)."}
                )

        return data
