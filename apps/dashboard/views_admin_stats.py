"""
Vue des statistiques administrateur pour le tableau de bord UniAbsences.

``admin_statistics``
    Affiche la page de statistiques avancées avec les données de graphiques : top professeurs
    par nombre d'absences, top cours, tendance mensuelle des absences, absences par
    département et répartition par statut de justification et niveau d'études.
    Les données sont restreintes à l'année académique active.

Note : les KPIs principaux du tableau de bord administrateur se trouvent dans ``views_admin_dashboard.py``.
"""

import logging

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique
from apps.dashboard.decorators import admin_required

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_GET
def admin_statistics(request):
    """
    Page dédiée aux statistiques avancées des absences.
    Séparée du dashboard principal pour une meilleure lisibilité et performance.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    year_filter = Q(id_inscription__id_annee=academic_year) if academic_year else Q()

    # 1. Top 5 professeurs avec le plus d'absences
    top_professors = list(
        Absence.objects.filter(year_filter)
        .values(
            prof_nom=F("id_inscription__id_cours__professeur__nom"),
            prof_prenom=F("id_inscription__id_cours__professeur__prenom"),
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    top_professors_labels = [
        f"{p['prof_prenom']} {p['prof_nom']}" for p in top_professors if p["prof_nom"]
    ]
    top_professors_data = [p["total"] for p in top_professors if p["prof_nom"]]

    # 2. Top 5 cours avec le plus d'absences
    top_courses = list(
        Absence.objects.filter(year_filter)
        .values(cours_nom=F("id_inscription__id_cours__nom_cours"))
        .annotate(total=Count("id_absence"))
        .order_by("-total")[:5]
    )
    top_courses_labels = [c["cours_nom"] for c in top_courses]
    top_courses_data = [c["total"] for c in top_courses]

    # 3. Évolution mensuelle des absences
    monthly_absences = list(
        Absence.objects.filter(year_filter)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(total=Count("id_absence"))
        .order_by("month")
    )
    monthly_labels = [
        m["month"].strftime("%b %Y") for m in monthly_absences if m["month"]
    ]
    monthly_data = [m["total"] for m in monthly_absences if m["month"]]

    # 4. Répartition par département
    dept_absences = list(
        Absence.objects.filter(year_filter)
        .values(
            dept_nom=F("id_inscription__id_cours__id_departement__nom_departement")
        )
        .annotate(total=Count("id_absence"))
        .order_by("-total")
    )
    dept_labels = [d["dept_nom"] for d in dept_absences if d["dept_nom"]]
    dept_data = [d["total"] for d in dept_absences if d["dept_nom"]]

    # 5. Répartition par statut
    status_absences = list(
        Absence.objects.filter(year_filter)
        .values("statut")
        .annotate(total=Count("id_absence"))
        .order_by("statut")
    )
    status_map = {
        Absence.Statut.NON_JUSTIFIEE: "Non justifiée",
        Absence.Statut.EN_ATTENTE: "En attente",
        Absence.Statut.JUSTIFIEE: "Justifiée",
    }
    status_labels = [
        status_map.get(s["statut"], s["statut"]) for s in status_absences
    ]
    status_data = [s["total"] for s in status_absences]

    # 6. Répartition par niveau
    level_absences = list(
        Absence.objects.filter(year_filter)
        .values(niveau=F("id_inscription__id_cours__niveau"))
        .annotate(total=Count("id_absence"))
        .order_by("niveau")
    )
    level_labels = [f"Année {l['niveau']}" for l in level_absences if l["niveau"]]
    level_data = [l["total"] for l in level_absences if l["niveau"]]

    # 7. Statistiques KPI synthétiques
    total_absences = Absence.objects.filter(year_filter).count()
    status_dict = {s["statut"]: s["total"] for s in status_absences}
    kpi_justified = status_dict.get(Absence.Statut.JUSTIFIEE, 0)
    kpi_pending = status_dict.get(Absence.Statut.EN_ATTENTE, 0)
    kpi_unjustified = status_dict.get(Absence.Statut.NON_JUSTIFIEE, 0)
    kpi_justified_pct = (
        round((kpi_justified / total_absences) * 100, 1) if total_absences else 0
    )

    chart_data = {
        "monthly_labels": monthly_labels,
        "monthly_data": monthly_data,
        "top_professors_labels": top_professors_labels,
        "top_professors_data": top_professors_data,
        "top_courses_labels": top_courses_labels,
        "top_courses_data": top_courses_data,
        "dept_labels": dept_labels,
        "dept_data": dept_data,
        "status_labels": status_labels,
        "status_data": status_data,
        "level_labels": level_labels,
        "level_data": level_data,
    }

    context = {
        "academic_year": academic_year,
        "chart_data": chart_data,
        "top_professors": top_professors,
        "top_courses": top_courses,
        "total_absences": total_absences,
        "kpi_justified": kpi_justified,
        "kpi_pending": kpi_pending,
        "kpi_unjustified": kpi_unjustified,
        "kpi_justified_pct": kpi_justified_pct,
    }

    return render(request, "dashboard/admin_statistics.html", context)
