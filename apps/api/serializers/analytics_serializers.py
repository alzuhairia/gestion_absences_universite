"""
Serializers d'analytiques pour l'API REST UniAbsences.

Ce module contient deux serializers DRF simples (non-ModelSerializer) qui
définissent les formes JSON exactes retournées par les endpoints d'analytiques :

- ``DashboardAnalyticsSerializer`` — valide et sérialise le payload KPI haut niveau
  produit par ``dashboard_analytics``. Chaque champ correspond 1 pour 1 à une
  métrique scalaire calculée depuis la base de données (compteurs, identifiants).

- ``StatisticsAnalyticsSerializer`` — valide et sérialise le payload statistique
  plus riche produit par ``statistics_analytics``. Les champs de type liste
  contiennent des dictionnaires pré-agrégés (par ex. ``{"name": "...", "count": N}``)
  que les composants de graphiques front-end peuvent consommer directement sans
  transformation supplémentaire.

Comme les deux serializers ne sont utilisés que pour la *sortie* (sérialisation,
pas désérialisation), aucune logique de validation d'écriture n'est requise. Ils
servent principalement de points d'ancrage pour le schéma OpenAPI pour
drf-spectacular et de contrat de documentation entre la couche API et ses
consommateurs.

Fait partie de l'API REST UniAbsences — Module Analytiques.
"""

from rest_framework import serializers


class DashboardAnalyticsSerializer(serializers.Serializer):
    """
    Serializer pour la réponse KPI du tableau de bord administrateur.

    Chaque champ représente une seule métrique scalaire calculée sur l'année
    académique actuellement active (ou globalement quand aucune année n'est active).

    Champs :
        academic_year (str | None) : Étiquette lisible de l'année académique active
            (par ex. ``"2024-2025"``), ou ``None`` quand aucune année n'est
            marquée comme active.
        total_students (int) : Nombre d'étudiants actifs (role=ETUDIANT,
            actif=True).
        total_professors (int) : Nombre de professeurs actifs (role=PROFESSEUR,
            actif=True).
        total_secretaries (int) : Nombre de secrétaires actifs
            (role=SECRETAIRE, actif=True).
        active_courses (int) : Nombre de cours avec ``actif=True``.
        total_inscriptions (int) : Nombre d'inscriptions avec le statut
            ``EN_COURS`` dans l'année active.
        total_absences (int) : Total d'enregistrements d'absences dans l'année active
            (tous statuts).
        students_at_risk (int) : Nombre d'enregistrements d'inscription où le
            taux d'absences non justifiées de l'étudiant atteint ou dépasse le
            seuil applicable (spécifique au cours ou par défaut du système),
            en tenant compte du statut d'exemption.
        critical_actions_7d (int) : Nombre d'entrées ``LogAudit`` avec
            ``niveau="CRITIQUE"`` créées dans les sept derniers jours.
    """

    # Nullable car aucune année académique n'est peut-être encore configurée
    academic_year = serializers.CharField(allow_null=True)

    total_students = serializers.IntegerField()
    total_professors = serializers.IntegerField()
    total_secretaries = serializers.IntegerField()
    active_courses = serializers.IntegerField()
    total_inscriptions = serializers.IntegerField()
    total_absences = serializers.IntegerField()

    # Calculé en itérant sur toutes les inscriptions actives et en appliquant les seuils
    # par cours — peut être coûteux sur de grands jeux de données
    students_at_risk = serializers.IntegerField()

    # Compte glissant sur 7 jours des événements d'audit critiques
    critical_actions_7d = serializers.IntegerField()


class StatisticsAnalyticsSerializer(serializers.Serializer):
    """
    Serializer pour la réponse statistiques d'absences détaillées utilisée par les graphiques.

    Chaque champ liste contient des dictionnaires pré-agrégés prêts pour la
    consommation directe par les bibliothèques de graphiques front-end (par ex.
    Chart.js, Recharts). Les éléments de chaque liste sont de simples dicts
    Python ; le serializer ne valide pas leur structure interne — c'est la
    responsabilité de la vue qui les construit.

    Champs :
        academic_year (str | None) : Étiquette de l'année académique active, ou
            ``None`` quand aucune année active n'existe.
        top_professors (list) : Jusqu'à 5 professeurs avec le plus d'absences
            enregistrées sur leurs cours. Chaque élément a la forme
            ``{"name": "<prenom> <nom>", "count": N}``.
        top_courses (list) : Jusqu'à 5 cours avec le nombre d'absences le plus élevé.
            Chaque élément a la forme ``{"name": "<nom_cours>", "count": N}``.
        monthly_absences (list) : Comptes d'absences groupés par mois calendaire.
            Chaque élément a la forme ``{"month": "YYYY-MM", "count": N}``,
            ordonné chronologiquement.
        absences_by_department (list) : Comptes d'absences groupés par département.
            Chaque élément a la forme ``{"name": "<nom_departement>", "count": N}``,
            ordonné par compte décroissant.
        absences_by_status (list) : Comptes d'absences groupés par statut (mappés
            aux étiquettes d'affichage françaises). Chaque élément a la forme
            ``{"status": "<label>", "count": N}``.
        absences_by_level (list) : Comptes d'absences groupés par niveau d'études.
            Chaque élément a la forme ``{"level": "Année N", "count": N}``.
    """

    # Nullable — aucune année académique active est un état de configuration valide
    academic_year = serializers.CharField(allow_null=True)

    # Listes pré-agrégées — la structure interne du dict est définie par la vue
    top_professors = serializers.ListField()
    top_courses = serializers.ListField()
    monthly_absences = serializers.ListField()
    absences_by_department = serializers.ListField()
    absences_by_status = serializers.ListField()
    absences_by_level = serializers.ListField()
