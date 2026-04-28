"""
Statistiques détaillées de l'étudiant (graphiques et indicateurs).

Fonctionnalités :
  - Graphique barres : taux d'absence par cours vs seuil
  - Graphique ligne  : évolution mensuelle des absences
  - KPIs : heures manquées, cours à risque, taux justifié
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold
from apps.academic_sessions.models import AnneeAcademique
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription

MONTHS_FR = {
    1: "Janvier", 2: "Février", 3: "Mars", 4: "Avril",
    5: "Mai", 6: "Juin", 7: "Juillet", 8: "Août",
    9: "Septembre", 10: "Octobre", 11: "Novembre", 12: "Décembre",
}


@login_required
@student_required
@require_GET
def student_statistics(request):
    """
    Page de statistiques détaillées — graphiques d'absence par cours et dans le temps.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    inscriptions_qs = Inscription.objects.filter(
        id_etudiant=request.user, status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_cours__professeur", "id_cours__id_departement")

    if academic_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=academic_year)

    inscriptions = list(inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in inscriptions]

    total_absences = Absence.objects.filter(id_inscription__in=inscription_ids).count()
    total_justified = Absence.objects.filter(
        id_inscription__in=inscription_ids, statut=Absence.Statut.JUSTIFIEE
    ).count()

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

    system_threshold = get_system_threshold()

    course_labels = []
    absence_percentages = []
    course_thresholds = []
    total_hours_missed = 0
    courses_at_risk = 0

    for ins in inscriptions:
        cours = ins.id_cours
        total_periods = cours.nombre_total_periodes
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        rate = (total_abs / total_periods * 100) if total_periods > 0 else 0
        seuil = cours.get_seuil_absence()
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

        course_labels.append(cours.code_cours)
        absence_percentages.append(round(rate, 1))
        course_thresholds.append(seuil_effectif)
        total_hours_missed += total_abs
        if rate >= seuil_effectif:
            courses_at_risk += 1

    # Évolution mensuelle
    trend_labels = []
    trend_data = []
    absences_by_month = (
        Absence.objects.filter(id_inscription__in=inscriptions)
        .annotate(month=TruncMonth("id_seance__date_seance"))
        .values("month")
        .annotate(total_hours=Sum("duree_absence"))
        .order_by("month")
    )
    for entry in absences_by_month:
        if entry["month"]:
            trend_labels.append(MONTHS_FR.get(entry["month"].month, entry["month"].strftime("%B")))
            trend_data.append(float(entry["total_hours"] or 0))

    return render(
        request,
        "dashboard/student_statistics.html",
        {
            "academic_year": academic_year,
            "total_hours_missed": round(total_hours_missed, 1),
            "courses_at_risk": courses_at_risk,
            "total_absences": total_absences,
            "total_justified": total_justified,
            "system_threshold": system_threshold,
            "course_labels_json": course_labels,
            "absence_percentages_json": absence_percentages,
            "course_thresholds_json": course_thresholds,
            "trend_labels_json": trend_labels,
            "trend_data_json": trend_data,
            "system_threshold_json": system_threshold,
            "has_inscriptions": bool(course_labels),
            "has_trend_data": bool(trend_data),
        },
    )
