from django_filters import rest_framework as filters

from apps.absences.models import Absence, Justification
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class StudentFilter(filters.FilterSet):
    nom = filters.CharFilter(lookup_expr="icontains")
    prenom = filters.CharFilter(lookup_expr="icontains")
    email = filters.CharFilter(lookup_expr="icontains")
    niveau = filters.NumberFilter()
    actif = filters.BooleanFilter()

    class Meta:
        model = User
        fields = ["nom", "prenom", "email", "niveau", "actif"]


class CoursFilter(filters.FilterSet):
    code_cours = filters.CharFilter(lookup_expr="icontains")
    nom_cours = filters.CharFilter(lookup_expr="icontains")
    niveau = filters.NumberFilter()
    professeur = filters.NumberFilter(field_name="professeur__id_utilisateur")
    departement = filters.NumberFilter(field_name="id_departement")
    annee = filters.NumberFilter(field_name="id_annee")
    actif = filters.BooleanFilter()

    class Meta:
        model = Cours
        fields = [
            "code_cours",
            "nom_cours",
            "niveau",
            "professeur",
            "departement",
            "annee",
            "actif",
        ]


class InscriptionFilter(filters.FilterSet):
    etudiant = filters.NumberFilter(field_name="id_etudiant")
    cours = filters.NumberFilter(field_name="id_cours")
    annee = filters.NumberFilter(field_name="id_annee")
    status = filters.ChoiceFilter(choices=Inscription.Status.choices)
    type_inscription = filters.ChoiceFilter(
        choices=Inscription.TypeInscription.choices
    )
    eligible_examen = filters.BooleanFilter()

    class Meta:
        model = Inscription
        fields = [
            "etudiant",
            "cours",
            "annee",
            "status",
            "type_inscription",
            "eligible_examen",
        ]


class AbsenceFilter(filters.FilterSet):
    inscription = filters.NumberFilter(field_name="id_inscription")
    seance = filters.NumberFilter(field_name="id_seance")
    statut = filters.ChoiceFilter(choices=Absence.Statut.choices)
    type_absence = filters.ChoiceFilter(choices=Absence.TypeAbsence.choices)
    etudiant = filters.NumberFilter(
        field_name="id_inscription__id_etudiant"
    )
    cours = filters.NumberFilter(field_name="id_inscription__id_cours")
    annee = filters.NumberFilter(field_name="id_inscription__id_annee")
    date_from = filters.DateFilter(
        field_name="id_seance__date_seance", lookup_expr="gte"
    )
    date_to = filters.DateFilter(
        field_name="id_seance__date_seance", lookup_expr="lte"
    )

    class Meta:
        model = Absence
        fields = [
            "inscription",
            "seance",
            "statut",
            "type_absence",
            "etudiant",
            "cours",
            "annee",
            "date_from",
            "date_to",
        ]


class JustificationFilter(filters.FilterSet):
    state = filters.ChoiceFilter(choices=Justification.State.choices)
    absence = filters.NumberFilter(field_name="id_absence")
    etudiant = filters.NumberFilter(
        field_name="id_absence__id_inscription__id_etudiant"
    )
    cours = filters.NumberFilter(
        field_name="id_absence__id_inscription__id_cours"
    )
    date_from = filters.DateFilter(
        field_name="date_soumission", lookup_expr="date__gte"
    )
    date_to = filters.DateFilter(
        field_name="date_soumission", lookup_expr="date__lte"
    )

    class Meta:
        model = Justification
        fields = ["state", "absence", "etudiant", "cours", "date_from", "date_to"]
