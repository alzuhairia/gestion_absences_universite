"""
Dashboard principal du professeur (KPIs et étudiants à risque).

Fonctionnalités :
  - KPI : cours actifs, séances données, séances à venir, absences totales
  - Liste des étudiants à risque ou sous exemption (lecture seule, indicatif)

STRICT : aucune action administrative permise dans ce module.
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_dashboard(request):
    """
    Vue du tableau de bord professeur — KPIs et étudiants à risque.
    STRICT : Aucune action administrative permise.
    """

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    today = timezone.localdate()

    active_courses_count = Cours.objects.filter(professeur=request.user, actif=True).count()

    if academic_year:
        sessions_given = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__lt=today,
        ).count()
        upcoming_sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__gte=today,
        ).count()
        total_absences = Absence.objects.filter(
            id_seance__id_cours__professeur=request.user,
            id_seance__id_annee=academic_year,
        ).count()
    else:
        sessions_given = 0
        upcoming_sessions = 0
        total_absences = 0

    all_inscriptions_qs = Inscription.objects.filter(
        id_cours__professeur=request.user, status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions_qs = all_inscriptions_qs.filter(id_annee=academic_year)

    all_inscriptions = list(all_inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in all_inscriptions]
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
    at_risk_list = []

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = cours.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            if rate >= seuil_effectif:
                at_risk_count += 1
                at_risk_list.append(
                    {
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "inscription_id": ins.id_inscription,
                        "is_exempted": ins.exemption_40,
                        "status_label": "BLOQUÉ",
                        "status_color": "danger",
                    }
                )
            elif ins.exemption_40 and rate >= seuil:
                at_risk_list.append(
                    {
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "inscription_id": ins.id_inscription,
                        "is_exempted": True,
                        "status_label": "SOUS EXEMPTION",
                        "status_color": "info",
                    }
                )

    return render(
        request,
        "dashboard/instructor_index.html",
        {
            "academic_year": academic_year,
            "active_courses_count": active_courses_count,
            "sessions_given": sessions_given,
            "upcoming_sessions": upcoming_sessions,
            "total_absences": total_absences,
            "at_risk_count": at_risk_count,
            "at_risk_list": at_risk_list[:5],
        },
    )
