from rest_framework import serializers

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import Seance
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.enrollments.models import Inscription


# ── Users / Students ─────────────────────────────────────────────────────────


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


# ── Academics ─────────────────────────────────────────────────────────────────


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


# ── Enrollments ───────────────────────────────────────────────────────────────


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


# ── Absences ──────────────────────────────────────────────────────────────────


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


# ── Justifications ────────────────────────────────────────────────────────────


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


# ── Notifications ─────────────────────────────────────────────────────────────


class NotificationSerializer(serializers.Serializer):
    id_notification = serializers.IntegerField(read_only=True)
    message = serializers.CharField(read_only=True)
    type = serializers.CharField(read_only=True)
    lue = serializers.BooleanField(read_only=True)
    date_envoi = serializers.DateTimeField(read_only=True)


# ── Analytics ─────────────────────────────────────────────────────────────────


class DashboardAnalyticsSerializer(serializers.Serializer):
    academic_year = serializers.CharField(allow_null=True)
    total_students = serializers.IntegerField()
    total_professors = serializers.IntegerField()
    total_secretaries = serializers.IntegerField()
    active_courses = serializers.IntegerField()
    total_inscriptions = serializers.IntegerField()
    total_absences = serializers.IntegerField()
    students_at_risk = serializers.IntegerField()
    critical_actions_7d = serializers.IntegerField()


class StatisticsAnalyticsSerializer(serializers.Serializer):
    academic_year = serializers.CharField(allow_null=True)
    top_professors = serializers.ListField()
    top_courses = serializers.ListField()
    monthly_absences = serializers.ListField()
    absences_by_department = serializers.ListField()
    absences_by_status = serializers.ListField()
    absences_by_level = serializers.ListField()
