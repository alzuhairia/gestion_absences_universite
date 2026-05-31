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
    summary="Dashboard KPIs (admin only)",
    tags=["Analytics"],
    responses=DashboardAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def dashboard_analytics(request):
    """
    Return aggregated KPI metrics for the admin dashboard.

    All figures that relate to academic activity (enrollments, absences,
    at-risk students) are scoped to the currently active academic year.
    Global counts (students, professors, secretaries, active courses) are
    not year-scoped because they represent the current state of the system.

    The at-risk count is computed by iterating over every active enrollment
    and comparing each student's unjustified absence rate against the
    effective threshold for their course (course-specific override when set,
    otherwise the system-wide default).  Enrollments with ``exemption_40``
    have their threshold raised by ``exemption_margin`` percentage points,
    capped at 100 %.

    Parameters:
        request (Request): The authenticated admin request.  No query
            parameters are used; the active year is detected automatically.

    Returns:
        Response: A JSON object conforming to ``DashboardAnalyticsSerializer``.
    """
    # Resolve the active academic year — may be None if none is configured
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # --- Scalar user counts (global, not year-scoped) ---
    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()
    total_professors = User.objects.filter(role=User.Role.PROFESSEUR, actif=True).count()
    total_secretaries = User.objects.filter(role=User.Role.SECRETAIRE, actif=True).count()
    active_courses = Cours.objects.filter(actif=True).count()

    # Build a reusable year filter; empty Q() when no active year exists
    year_filter = Q(id_annee=academic_year) if academic_year else Q()

    # --- Year-scoped enrollment and absence totals ---
    total_inscriptions = Inscription.objects.filter(
        year_filter, status=Inscription.Status.EN_COURS
    ).count()
    total_absences = Absence.objects.filter(
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    ).count()

    # --- At-risk student count ---
    # Fetch the system-wide fallback threshold (used when a course has no override)
    system_threshold = get_system_threshold()

    # Load all active enrollments for the active year; include course data in one query
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()

    # Aggregate total unjustified absence hours per enrollment in a single DB query
    # Only count sessions that have already occurred (date_seance <= today)
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Iterate in Python because per-course threshold logic cannot be expressed in SQL
    at_risk_count = 0
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            # Compute the absence rate as a percentage of total course periods
            rate = (total_abs / cours.nombre_total_periodes) * 100
            # Use course-level threshold if defined, otherwise fall back to system default
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            # Students with exemption_40 get a higher effective threshold (capped at 100 %)
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_count += 1

    # --- Critical audit log actions in the last 7 days ---
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
    summary="Absence statistics & charts data (admin only)",
    tags=["Analytics"],
    responses=StatisticsAnalyticsSerializer,
)
@api_view(["GET"])
@permission_classes([IsAdmin])
def statistics_analytics(request):
    """
    Return pre-aggregated absence statistics for chart rendering.

    All datasets are scoped to the currently active academic year.  When no
    active year exists, all absences are included.  The six datasets are
    computed independently with separate DB queries and formatted into the
    shape expected by front-end chart components.

    Dataset descriptions:
      - ``top_professors``        : Top 5 professors ranked by total absence
                                    count on their courses.  Professors with
                                    no name (e.g. courses without an assigned
                                    professor) are filtered out.
      - ``top_courses``           : Top 5 courses ranked by total absence
                                    count.
      - ``monthly_absences``      : Absence count per calendar month,
                                    ordered chronologically.  Sessions without
                                    a date are excluded.
      - ``absences_by_department``: Absence count per department, ordered by
                                    count descending.  Null department names
                                    are excluded.
      - ``absences_by_status``    : Absence count per status, with internal
                                    enum values mapped to French display labels.
      - ``absences_by_level``     : Absence count per study level (1, 2, 3),
                                    formatted as "Année N".

    Parameters:
        request (Request): The authenticated admin request.

    Returns:
        Response: A JSON object conforming to ``StatisticsAnalyticsSerializer``.
    """
    # Resolve the active academic year — None is a valid state
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # Reusable filter; traverses Absence → Inscription → AnneeAcademique
    year_filter = (
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    )

    # --- Top 5 professors by absence count ---
    # Traverse: Absence → Inscription → Cours → User (professor)
    top_professors = list(
        Absence.objects.filter(year_filter)
        .values(
            nom=F("id_inscription__id_cours__professeur__nom"),
            prenom=F("id_inscription__id_cours__professeur__prenom"),
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    # Filter out rows where the professor name is null (unassigned courses)
    top_professors = [
        {"name": f"{p['prenom']} {p['nom']}", "count": p["total"]}
        for p in top_professors
        if p["nom"]
    ]

    # --- Top 5 courses by absence count ---
    top_courses = list(
        Absence.objects.filter(year_filter)
        .values(name=F("id_inscription__id_cours__nom_cours"))
        .annotate(count=Count("id_absence"))
        .order_by("-count")[:5]
    )

    # --- Monthly absence trend ---
    # TruncMonth groups absences by the calendar month of their session date
    monthly_absences = list(
        Absence.objects.filter(year_filter)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(count=Count("id_absence"))
        .order_by("month")
    )
    # Format datetime objects to "YYYY-MM" strings; exclude sessions with no date
    monthly_absences = [
        {"month": m["month"].strftime("%Y-%m"), "count": m["count"]}
        for m in monthly_absences
        if m["month"]
    ]

    # --- Absences by department ---
    # Traverse: Absence → Inscription → Cours → Departement
    dept_absences = list(
        Absence.objects.filter(year_filter)
        .values(
            name=F("id_inscription__id_cours__id_departement__nom_departement")
        )
        .annotate(count=Count("id_absence"))
        .order_by("-count")
    )
    # Drop rows where the department name resolved to null
    dept_absences = [d for d in dept_absences if d["name"]]

    # --- Absences by status — map internal enum values to French display labels ---
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
    # Replace the enum key with a human-readable French label for the front end
    status_absences = [
        {"status": status_map.get(s["statut"], s["statut"]), "count": s["count"]}
        for s in status_absences
    ]

    # --- Absences by study level ---
    # Traverse: Absence → Inscription → Cours (niveau field: 1, 2, or 3)
    level_absences = list(
        Absence.objects.filter(year_filter)
        .values(niveau=F("id_inscription__id_cours__niveau"))
        .annotate(count=Count("id_absence"))
        .order_by("niveau")
    )
    # Format as "Année N" for chart labels; exclude null-level records
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
