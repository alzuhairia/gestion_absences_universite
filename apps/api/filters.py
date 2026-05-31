"""
Classes de filtres pour l'API REST UniAbsences.

Ce module définit des sous-classes FilterSet de django-filters qui sont reliées
à chaque ViewSet DRF via ``filterset_class``. Elles permettent aux consommateurs
de l'API d'affiner les résultats de requête via des paramètres d'URL sans écrire
de logique de queryset personnalisée dans chaque vue.

Responsabilités :
  - StudentFilter    : filtrer les utilisateurs étudiants par nom, email, niveau
                       d'études et statut actif.
  - CoursFilter      : filtrer les cours par code, nom, niveau, professeur attribué,
                       département, année académique et indicateur actif.
  - InscriptionFilter: filtrer les inscriptions par étudiant, cours, année académique,
                       statut d'inscription, type d'inscription et éligibilité aux
                       examens.
  - AbsenceFilter    : filtrer les absences par inscription, séance, statut de
                       justification, type d'absence, étudiant, cours, année
                       académique et plage de dates de séance (date_from / date_to).
  - JustificationFilter: filtrer les enregistrements de justification par état
                       d'approbation, absence liée, étudiant, cours et plage de
                       dates de soumission.

Fait partie de l'API REST UniAbsences.
"""

from django_filters import rest_framework as filters

from apps.absences.models import Absence, Justification
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.enrollments.models import Inscription


class StudentFilter(filters.FilterSet):
    """
    FilterSet pour le modèle Student (User).

    Paramètres de requête pris en charge :
      - ``nom``    : correspondance partielle insensible à la casse sur le nom de famille.
      - ``prenom`` : correspondance partielle insensible à la casse sur le prénom.
      - ``email``  : correspondance partielle insensible à la casse sur l'adresse email.
      - ``niveau`` : correspondance exacte sur le niveau d'études (1, 2 ou 3).
      - ``actif``  : booléen — inclure uniquement les étudiants actifs ou inactifs.
    """

    nom = filters.CharFilter(lookup_expr="icontains")
    prenom = filters.CharFilter(lookup_expr="icontains")
    email = filters.CharFilter(lookup_expr="icontains")
    niveau = filters.NumberFilter()
    actif = filters.BooleanFilter()

    class Meta:
        """Configuration django-filter : modèle cible et champs filtrables exposés."""

        model = User
        fields = ["nom", "prenom", "email", "niveau", "actif"]


class CoursFilter(filters.FilterSet):
    """
    FilterSet pour le modèle Cours.

    Paramètres de requête pris en charge :
      - ``code_cours``  : correspondance partielle insensible à la casse sur le code du cours.
      - ``nom_cours``   : correspondance partielle insensible à la casse sur le nom du cours.
      - ``niveau``      : correspondance exacte sur le niveau d'études (1, 2 ou 3).
      - ``professeur``  : correspondance exacte sur la clé primaire du professeur
                          (``professeur__id_utilisateur``).
      - ``departement`` : correspondance exacte sur la clé primaire du département.
      - ``annee``       : correspondance exacte sur la clé primaire de l'année académique.
      - ``actif``       : booléen — inclure uniquement les cours actifs ou inactifs.
    """

    code_cours = filters.CharFilter(lookup_expr="icontains")
    nom_cours = filters.CharFilter(lookup_expr="icontains")
    niveau = filters.NumberFilter()
    # Filtre par ID de professeur via le parcours de la clé étrangère
    professeur = filters.NumberFilter(field_name="professeur__id_utilisateur")
    departement = filters.NumberFilter(field_name="id_departement")
    annee = filters.NumberFilter(field_name="id_annee")
    actif = filters.BooleanFilter()

    class Meta:
        """Configuration django-filter : modèle ``Cours`` et liste des paramètres de filtrage."""

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
    """
    FilterSet pour le modèle Inscription.

    Paramètres de requête pris en charge :
      - ``etudiant``        : correspondance exacte sur la clé primaire de l'étudiant.
      - ``cours``           : correspondance exacte sur la clé primaire du cours.
      - ``annee``           : correspondance exacte sur la clé primaire de l'année académique.
      - ``status``          : choix de statut d'inscription (par ex. EN_COURS,
                              ABANDONNE).
      - ``type_inscription``: choix de type d'inscription (par ex. NORMALE,
                              RATTRAPAGE).
      - ``eligible_examen`` : booléen — indique si l'étudiant est éligible à l'examen.
    """

    etudiant = filters.NumberFilter(field_name="id_etudiant")
    cours = filters.NumberFilter(field_name="id_cours")
    annee = filters.NumberFilter(field_name="id_annee")
    # Le filtre de choix impose uniquement des valeurs de statut valides issues de l'énum du modèle
    status = filters.ChoiceFilter(choices=Inscription.Status.choices)
    type_inscription = filters.ChoiceFilter(
        choices=Inscription.TypeInscription.choices
    )
    eligible_examen = filters.BooleanFilter()

    class Meta:
        """Configuration django-filter : modèle ``Inscription`` et champs filtrables exposés."""

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
    """
    FilterSet pour le modèle Absence.

    Paramètres de requête pris en charge :
      - ``inscription``  : correspondance exacte sur la clé primaire d'inscription.
      - ``seance``       : correspondance exacte sur la clé primaire de la séance.
      - ``statut``       : choix de statut d'absence (NON_JUSTIFIEE, EN_ATTENTE,
                           JUSTIFIEE).
      - ``type_absence`` : choix de type d'absence (ABSENT, PARTIEL).
      - ``etudiant``     : filtrer par PK étudiant via la relation d'inscription
                           (``id_inscription__id_etudiant``).
      - ``cours``        : filtrer par PK de cours via l'inscription
                           (``id_inscription__id_cours``).
      - ``annee``        : filtrer par PK d'année académique via l'inscription
                           (``id_inscription__id_annee``).
      - ``date_from``    : inclure uniquement les absences dont la date de séance est
                           égale ou postérieure à cette date (ISO 8601).
      - ``date_to``      : inclure uniquement les absences dont la date de séance est
                           égale ou antérieure à cette date (ISO 8601).
    """

    inscription = filters.NumberFilter(field_name="id_inscription")
    seance = filters.NumberFilter(field_name="id_seance")
    # Les filtres de choix valident contre les valeurs d'énum propres au modèle
    statut = filters.ChoiceFilter(choices=Absence.Statut.choices)
    type_absence = filters.ChoiceFilter(choices=Absence.TypeAbsence.choices)
    # Filtres de relation croisée — traverser la FK d'inscription pour atteindre étudiant/cours/année
    etudiant = filters.NumberFilter(
        field_name="id_inscription__id_etudiant"
    )
    cours = filters.NumberFilter(field_name="id_inscription__id_cours")
    annee = filters.NumberFilter(field_name="id_inscription__id_annee")
    # Filtres de plage de dates sur le champ de date de la séance liée
    date_from = filters.DateFilter(
        field_name="id_seance__date_seance", lookup_expr="gte"
    )
    date_to = filters.DateFilter(
        field_name="id_seance__date_seance", lookup_expr="lte"
    )

    class Meta:
        """Configuration django-filter : modèle ``Absence`` et l'ensemble des filtres URL."""

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
    """
    FilterSet pour le modèle Justification.

    Paramètres de requête pris en charge :
      - ``state``     : choix d'état d'approbation (EN_ATTENTE, ACCEPTEE, REFUSEE).
      - ``absence``   : correspondance exacte sur la clé primaire d'absence liée.
      - ``etudiant``  : filtrer par PK étudiant en traversant absence → inscription
                        (``id_absence__id_inscription__id_etudiant``).
      - ``cours``     : filtrer par PK de cours en traversant absence → inscription
                        (``id_absence__id_inscription__id_cours``).
      - ``date_from`` : inclure uniquement les justifications soumises à cette date
                        ou après (applique ``date__gte`` au champ datetime).
      - ``date_to``   : inclure uniquement les justifications soumises à cette date
                        ou avant (applique ``date__lte`` au champ datetime).
    """

    state = filters.ChoiceFilter(choices=Justification.State.choices)
    absence = filters.NumberFilter(field_name="id_absence")
    # Filtres de relation croisée approfondie pour le filtrage côté staff par étudiant ou cours
    etudiant = filters.NumberFilter(
        field_name="id_absence__id_inscription__id_etudiant"
    )
    cours = filters.NumberFilter(
        field_name="id_absence__id_inscription__id_cours"
    )
    # Troncature de date via ``date__gte`` / ``date__lte`` sur le DateTimeField
    date_from = filters.DateFilter(
        field_name="date_soumission", lookup_expr="date__gte"
    )
    date_to = filters.DateFilter(
        field_name="date_soumission", lookup_expr="date__lte"
    )

    class Meta:
        """Configuration django-filter : modèle ``Justification`` et champs filtrables exposés."""

        model = Justification
        fields = ["state", "absence", "etudiant", "cours", "date_from", "date_to"]
