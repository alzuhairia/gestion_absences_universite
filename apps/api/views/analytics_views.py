"""
Points de terminaison API d'analytique pour l'API REST UniAbsences.

Ce module expose deux points de terminaison en lecture réservés aux admins,
utilisés par le tableau de bord d'administration pour afficher les cartes KPI
et les données des graphiques sans passer par la couche de templates Django.

Points de terminaison
---------------------
``dashboard_analytics`` (GET /api/analytics/dashboard/)
    Instantané KPI agrégé : nombre d'utilisateurs, nombre de cours actifs,
    total des inscriptions et des absences, nombre d'étudiants à risque, et
    actions critiques du journal d'audit sur les 7 derniers jours. Tous les
    chiffres sont filtrés sur l'année académique actuellement active lorsque
    cela est pertinent.

``statistics_analytics`` (GET /api/analytics/statistics/)
    Jeu de données pour le rendu des graphiques : top 5 des professeurs par
    nombre d'absences, top 5 des cours, tendance mensuelle des absences,
    absences par département, absences par statut de justification, absences
    par niveau d'étude.

Les deux points de terminaison requièrent la classe de permission ``IsAdmin``
(rôle ADMIN).

Partie de l'API REST UniAbsences.
"""
import datetime
from typing import Any

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.enrollments.models import Inscription

from ..permissions import IsAdmin
from ..serializers import DashboardAnalyticsSerializer, StatisticsAnalyticsSerializer


@extend_schema(
    summary="KPI du tableau de bord (admin uniquement)",
    tags=["Analytics"],
    responses=DashboardAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def dashboard_analytics(request):
    """
    Renvoie les indicateurs KPI agrégés pour le tableau de bord admin.

    Tous les chiffres liés à l'activité académique (inscriptions, absences,
    étudiants à risque) sont restreints à l'année académique actuellement
    active. Les comptes globaux (étudiants, professeurs, secrétaires, cours
    actifs) ne sont pas restreints à l'année car ils représentent l'état
    actuel du système.

    Le compte d'étudiants à risque est calculé en itérant sur chaque
    inscription active et en comparant le taux d'absences non justifiées de
    chaque étudiant au seuil effectif de son cours (surcharge spécifique au
    cours si définie, sinon le défaut à l'échelle du système). Les
    inscriptions avec ``exemption_40`` voient leur seuil relevé de
    ``exemption_margin`` points de pourcentage, plafonné à 100 %.

    Paramètres :
        request (Request) : la requête admin authentifiée. Aucun paramètre de
            requête n'est utilisé ; l'année active est détectée automatiquement.

    Retour :
        Response : un objet JSON conforme à ``DashboardAnalyticsSerializer``.
    """
    # Résout l'année académique active — peut être None si aucune n'est configurée
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # --- Comptes d'utilisateurs scalaires (globaux, non restreints à l'année) ---
    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()
    total_professors = User.objects.filter(role=User.Role.PROFESSEUR, actif=True).count()
    total_secretaries = User.objects.filter(role=User.Role.SECRETAIRE, actif=True).count()
    active_courses = Cours.objects.filter(actif=True).count()

    # Construit un filtre d'année réutilisable ; Q() vide si aucune année active
    year_filter = Q(id_annee=academic_year) if academic_year else Q()

    # --- Totaux d'inscriptions et d'absences restreints à l'année ---
    total_inscriptions = Inscription.objects.filter(
        year_filter, status=Inscription.Status.EN_COURS
    ).count()
    total_absences = Absence.objects.filter(
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    ).count()

    # --- Compte d'étudiants à risque ---
    # Récupère le seuil de repli système (utilisé quand un cours n'a pas de surcharge)
    system_threshold = get_system_threshold()

    # Charge toutes les inscriptions actives de l'année active ; inclut les données de cours en une requête
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()

    # Agrège le total d'heures d'absence non justifiées par inscription en une seule requête DB
    # Ne compte que les séances déjà passées (date_seance <= today)
    absence_sums: dict[int, Any] = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Itération en Python car la logique de seuil par cours ne s'exprime pas en SQL
    at_risk_count = 0
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            # Calcule le taux d'absence en pourcentage du total de périodes du cours
            rate = (total_abs / cours.nombre_total_periodes) * 100
            # Utilise le seuil au niveau du cours s'il est défini, sinon replie sur le défaut système
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            # Les étudiants avec exemption_40 ont un seuil effectif plus élevé (plafonné à 100 %)
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_count += 1

    # --- Actions critiques du journal d'audit sur les 7 derniers jours ---
    seven_days_ago = timezone.now() - datetime.timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago, niveau="CRITIQUE"
    ).count()

    data = {
        "academic_year": academic_year.libelle if academic_year else None,
        "total_students": total_students,
        "total_professors": total_professors,
        "total_secretaries": total_secretaries,
        "active_courses": active_courses,
        "total_inscriptions": total_inscriptions,
        "total_absences": total_absences,
        "students_at_risk": at_risk_count,
        "critical_actions_7d": critical_actions,
    }
    return Response(DashboardAnalyticsSerializer(data).data)


@extend_schema(
    summary="Statistiques d'absences et données graphiques (admin uniquement)",
    tags=["Analytics"],
    responses=StatisticsAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def statistics_analytics(request):
    """
    Renvoie les statistiques d'absences pré-agrégées pour le rendu des graphiques.

    Tous les jeux de données sont restreints à l'année académique
    actuellement active. Lorsqu'aucune année n'est active, toutes les
    absences sont incluses. Les six jeux de données sont calculés
    indépendamment par des requêtes DB séparées et formatés selon la forme
    attendue par les composants graphiques du front-end.

    Description des jeux de données :
      - ``top_professors``        : Top 5 des professeurs classés par nombre
                                    total d'absences sur leurs cours. Les
                                    professeurs sans nom (par ex. cours sans
                                    professeur assigné) sont filtrés.
      - ``top_courses``           : Top 5 des cours classés par nombre total
                                    d'absences.
      - ``monthly_absences``      : Nombre d'absences par mois calendaire,
                                    ordonnés chronologiquement. Les séances
                                    sans date sont exclues.
      - ``absences_by_department``: Nombre d'absences par département,
                                    ordonné par compte décroissant. Les noms
                                    de département nuls sont exclus.
      - ``absences_by_status``    : Nombre d'absences par statut, avec les
                                    valeurs d'enum internes mappées vers des
                                    libellés d'affichage en français.
      - ``absences_by_level``     : Nombre d'absences par niveau d'étude
                                    (1, 2, 3), formaté en "Année N".

    Paramètres :
        request (Request) : la requête admin authentifiée.

    Retour :
        Response : un objet JSON conforme à ``StatisticsAnalyticsSerializer``.
    """
    # Résout l'année académique active — None est un état valide
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # Filtre réutilisable ; traverse Absence → Inscription → AnneeAcademique
    year_filter = (
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    )

    # --- Top 5 des professeurs par nombre d'absences ---
    # Traverse : Absence → Inscription → Cours → User (professeur)
    top_professors = list(
        Absence.objects.filter(year_filter)
        .values(
            nom=F("id_inscription__id_cours__professeur__nom"),
            prenom=F("id_inscription__id_cours__professeur__prenom"),
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    # Filtre les lignes où le nom du professeur est nul (cours sans assignation)
    top_professors = [
        {"name": f"{p['prenom']} {p['nom']}", "count": p["total"]}
        for p in top_professors
        if p["nom"]
    ]

    # --- Top 5 des cours par nombre d'absences ---
    top_courses = list(
        Absence.objects.filter(year_filter)
        .values(name=F("id_inscription__id_cours__nom_cours"))
        .annotate(count=Count("id_absence"))
        .order_by("-count")[:5]
    )

    # --- Tendance mensuelle des absences ---
    # TruncMonth regroupe les absences par mois calendaire de la date de séance
    monthly_absences = list(
        Absence.objects.filter(year_filter)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(count=Count("id_absence"))
        .order_by("month")
    )
    # Formate les datetimes en chaînes "YYYY-MM" ; exclut les séances sans date
    monthly_absences = [
        {"month": m["month"].strftime("%Y-%m"), "count": m["count"]}
        for m in monthly_absences
        if m["month"]
    ]

    # --- Absences par département ---
    # Traverse : Absence → Inscription → Cours → Departement
    dept_absences = list(
        Absence.objects.filter(year_filter)
        .values(
            name=F("id_inscription__id_cours__id_departement__nom_departement")
        )
        .annotate(count=Count("id_absence"))
        .order_by("-count")
    )
    # Supprime les lignes où le nom de département est nul
    dept_absences = [d for d in dept_absences if d["name"]]

    # --- Absences par statut — mappe les valeurs d'enum internes vers des libellés français ---
    status_map = {
        Absence.Statut.NON_JUSTIFIEE: "Non justifiée",
        Absence.Statut.EN_ATTENTE: "En attente",
        Absence.Statut.JUSTIFIEE: "Justifiée",
    }
    status_absences = list(
        Absence.objects.filter(year_filter)
        .values("statut")
        .annotate(count=Count("id_absence"))
        .order_by("statut")
    )
    # Remplace la clé d'enum par un libellé français lisible pour le front-end
    status_absences = [
        {"status": status_map.get(s["statut"], s["statut"]), "count": s["count"]}
        for s in status_absences
    ]

    # --- Absences par niveau d'étude ---
    # Traverse : Absence → Inscription → Cours (champ niveau : 1, 2 ou 3)
    level_absences = list(
        Absence.objects.filter(year_filter)
        .values(niveau=F("id_inscription__id_cours__niveau"))
        .annotate(count=Count("id_absence"))
        .order_by("niveau")
    )
    # Formate en "Année N" pour les libellés graphiques ; exclut les enregistrements sans niveau
    level_absences = [
        {"level": f"Année {lv['niveau']}", "count": lv["count"]}
        for lv in level_absences
        if lv["niveau"]
    ]

    data = {
        "academic_year": academic_year.libelle if academic_year else None,
        "top_professors": top_professors,
        "top_courses": top_courses,
        "monthly_absences": monthly_absences,
        "absences_by_department": dept_absences,
        "absences_by_status": status_absences,
        "absences_by_level": level_absences,
    }
    return Response(StatisticsAnalyticsSerializer(data).data)
