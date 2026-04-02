"""
FICHIER : apps/dashboard/views_admin_stats.py
RESPONSABILITE : Dashboard principal admin et statistiques avancees
FONCTIONNALITES PRINCIPALES :
  - Dashboard admin : KPIs globaux, vue d'ensemble
  - Statistiques avancees avec graphiques et analyses
DEPENDANCES CLES : absences.services, enrollments.models
"""

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.dashboard.decorators import admin_required
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def is_admin(user):
    """
    Vérifie si l'utilisateur est un administrateur.
    IMPORTANT: Séparé de is_secretary() pour éviter la confusion des rôles.
    """
    return user.is_authenticated and user.role == User.Role.ADMIN


# ---------------------------------------------------------------------------
# Dashboard admin - KPIs et vue d'ensemble
# ---------------------------------------------------------------------------


@login_required
@admin_required
@require_GET
def admin_dashboard_main(request):
    """
    Tableau de bord principal de l'administrateur avec KPIs et vue d'ensemble.
    IMPORTANT: L'administrateur configure et audite, il ne gère PAS les opérations quotidiennes.
    """

    # Récupérer l'année académique active
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # KPI 1: Nombre total d'étudiants
    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()

    # KPI 2: Nombre total de professeurs
    total_professors = User.objects.filter(
        role=User.Role.PROFESSEUR, actif=True
    ).count()

    # KPI 3: Nombre de secrétaires
    total_secretaries = User.objects.filter(
        role=User.Role.SECRETAIRE, actif=True
    ).count()

    # KPI 4: Nombre de cours actifs
    # Pour le dashboard admin, on compte tous les cours actifs (configurés et prêts à être utilisés)
    # Un cours est considéré comme "actif" s'il est marqué comme actif dans le système
    active_courses = Cours.objects.filter(actif=True).count()

    # Optionnel : Compter aussi les cours avec professeur assigné ET utilisés dans l'année active
    # (pour avoir une vue plus détaillée)
    if academic_year:
        active_courses_with_activity = (
            Cours.objects.filter(actif=True, professeur__isnull=False)
            .filter(
                Q(
                    id_cours__in=Inscription.objects.filter(
                        id_annee=academic_year
                    ).values_list("id_cours", flat=True)
                )
                | Q(
                    id_cours__in=academic_year.seances.values_list(
                        "id_cours", flat=True
                    )
                )
            )
            .distinct()
            .count()
        )
    else:
        active_courses_with_activity = 0

    # KPI 5: Nombre d'alertes système (étudiants à risque) — filtré par année active
    at_risk_count = 0
    all_inscriptions = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    from apps.absences.services import get_system_threshold

    system_threshold = get_system_threshold()
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

    # KPI 6: Nombre d'actions critiques (journaux d'audit des 7 derniers jours)
    seven_days_ago = timezone.now() - timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago, niveau="CRITIQUE"
    ).count()

    # KPI 7: Total d'inscriptions actives
    if academic_year:
        total_inscriptions = Inscription.objects.filter(
            id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).count()
    else:
        total_inscriptions = 0

    # KPI 8: Total d'absences enregistrées (année active)
    if academic_year:
        total_absences = Absence.objects.filter(
            id_inscription__id_annee=academic_year
        ).count()
    else:
        total_absences = 0

    # Journaux d'audit récents
    recent_audits = LogAudit.objects.select_related("id_utilisateur").order_by(
        "-date_action"
    )[:10]

    # Paramètres système
    settings = SystemSettings.get_settings()

    context = {
        "total_students": total_students,
        "total_professors": total_professors,
        "total_secretaries": total_secretaries,
        "active_courses": active_courses,
        "system_alerts": at_risk_count,
        "critical_actions": critical_actions,
        "total_inscriptions": total_inscriptions,
        "total_absences": total_absences,
        "recent_audits": recent_audits,
        "academic_year": academic_year,
        "settings": settings,
    }

    return render(request, "dashboard/admin_dashboard.html", context)


# ---------------------------------------------------------------------------
# Statistiques avancees avec graphiques
# ---------------------------------------------------------------------------


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
    level_labels = [
        f"Année {l['niveau']}" for l in level_absences if l["niveau"]
    ]
    level_data = [l["total"] for l in level_absences if l["niveau"]]

    # Combine chart data into a single dict for safe JSON serialization via |json_script
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
    }

    return render(request, "dashboard/admin_statistics.html", context)
