"""
FICHIER : apps/api/views/analytics_views.py
RESPONSABILITE : Endpoints analytiques — KPIs tableau de bord et statistiques avancees.
  - dashboard_analytics   : indicateurs cles (admin uniquement)
  - statistics_analytics  : donnees graphiques (top profs, evolution mensuelle, etc.)
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
    """Admin dashboard KPIs as JSON."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()
    total_professors = User.objects.filter(role=User.Role.PROFESSEUR, actif=True).count()
    total_secretaries = User.objects.filter(role=User.Role.SECRETAIRE, actif=True).count()
    active_courses = Cours.objects.filter(actif=True).count()

    year_filter = Q(id_annee=academic_year) if academic_year else Q()

    total_inscriptions = Inscription.objects.filter(
        year_filter, status=Inscription.Status.EN_COURS
    ).count()
    total_absences = Absence.objects.filter(
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    ).count()

    system_threshold = get_system_threshold()
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    today = timezone.localdate()
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
    at_risk_count = 0
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_count += 1

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
    """Advanced absence statistics as JSON (for charts)."""
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    year_filter = (
        Q(id_inscription__id_annee=academic_year) if academic_year else Q()
    )

    top_professors = list(
        Absence.objects.filter(year_filter)
        .values(
            nom=F("id_inscription__id_cours__professeur__nom"),
            prenom=F("id_inscription__id_cours__professeur__prenom"),
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    top_professors = [
        {"name": f"{p['prenom']} {p['nom']}", "count": p["total"]}
        for p in top_professors
        if p["nom"]
    ]

    top_courses = list(
        Absence.objects.filter(year_filter)
        .values(name=F("id_inscription__id_cours__nom_cours"))
        .annotate(count=Count("id_absence"))
        .order_by("-count")[:5]
    )

    monthly_absences = list(
        Absence.objects.filter(year_filter)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(count=Count("id_absence"))
        .order_by("month")
    )
    monthly_absences = [
        {"month": m["month"].strftime("%Y-%m"), "count": m["count"]}
        for m in monthly_absences
        if m["month"]
    ]

    dept_absences = list(
        Absence.objects.filter(year_filter)
        .values(
            name=F("id_inscription__id_cours__id_departement__nom_departement")
        )
        .annotate(count=Count("id_absence"))
        .order_by("-count")
    )
    dept_absences = [d for d in dept_absences if d["name"]]

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
    status_absences = [
        {"status": status_map.get(s["statut"], s["statut"]), "count": s["count"]}
        for s in status_absences
    ]

    level_absences = list(
        Absence.objects.filter(year_filter)
        .values(niveau=F("id_inscription__id_cours__niveau"))
        .annotate(count=Count("id_absence"))
        .order_by("niveau")
    )
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
