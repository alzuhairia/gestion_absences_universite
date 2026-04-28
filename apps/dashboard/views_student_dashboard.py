"""
Dashboard principal de l'étudiant (KPIs et statut académique).

Fonctionnalités :
  - KPI : cours inscrits, séances totales, absences, taux global
  - Statut académique : OK / À RISQUE / BLOQUÉ
  - Notifications récentes (5 dernières)

STRICT : l'étudiant consulte uniquement ses propres données.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.dashboard.decorators import student_required
from apps.enrollments.models import Inscription
from apps.notifications.models import Notification


@login_required
@student_required
@require_GET
def student_dashboard(request):
    """
    Dashboard étudiant — KPIs et statut académique.
    STRICT : consultation uniquement, aucun pouvoir décisionnel.
    """

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        inscriptions = list(
            Inscription.objects.filter(
                id_etudiant=request.user,
                id_annee=academic_year,
                status=Inscription.Status.EN_COURS,
            ).select_related("id_cours", "id_cours__professeur", "id_cours__id_departement")
        )
    else:
        inscriptions = list(
            Inscription.objects.filter(
                id_etudiant=request.user, status=Inscription.Status.EN_COURS
            ).select_related("id_cours", "id_cours__professeur", "id_cours__id_departement")
        )

    total_courses = len(inscriptions)

    if academic_year:
        course_ids = [ins.id_cours_id for ins in inscriptions]
        total_sessions = Seance.objects.filter(
            id_cours__in=course_ids, id_annee=academic_year
        ).count()
    else:
        total_sessions = 0

    inscription_ids = [ins.id_inscription for ins in inscriptions]
    total_absences = Absence.objects.filter(id_inscription__in=inscription_ids).count()

    total_abs_hours = 0
    total_periods = 0
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

    for ins in inscriptions:
        cours = ins.id_cours
        total_periods += cours.nombre_total_periodes
        abs_hours = float(absence_sums.get(ins.id_inscription, 0) or 0)
        total_abs_hours += abs_hours

    overall_rate = (total_abs_hours / total_periods) * 100 if total_periods > 0 else 0

    academic_status = "OK"
    status_color = "success"
    is_blocked = False
    is_at_risk = False

    for ins in inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            abs_hours = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (abs_hours / cours.nombre_total_periodes) * 100
            seuil = cours.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            if rate >= seuil_effectif:
                is_blocked = True
                academic_status = "BLOQUÉ"
                status_color = "danger"
                break
            elif seuil > 0 and rate >= (seuil * 0.75):
                is_at_risk = True

    if not is_blocked and is_at_risk:
        academic_status = "À RISQUE"
        status_color = "warning"

    notifications = Notification.objects.filter(id_utilisateur=request.user).order_by(
        "-date_envoi"
    )[:5]

    return render(
        request,
        "dashboard/student_index.html",
        {
            "academic_year": academic_year,
            "total_courses": total_courses,
            "total_sessions": total_sessions,
            "total_absences": total_absences,
            "overall_rate": round(overall_rate, 1),
            "academic_status": academic_status,
            "status_color": status_color,
            "is_blocked": is_blocked,
            "notifications": notifications,
        },
    )
