"""
Séances et statistiques globales du professeur.

Fonctionnalités :
  - Liste paginée de toutes les séances avec regroupement par cours
  - Statistiques globales : taux d'absence moyen, étudiants à risque, absences totales
"""

from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.utils import safe_get_page
from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_sessions(request):
    """
    Page "Séances" — liste paginée de toutes les séances du professeur.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    if academic_year:
        sessions = (
            Seance.objects.filter(
                id_cours__professeur=request.user, id_annee=academic_year
            )
            .select_related("id_cours", "id_cours__id_departement")
            .order_by("-date_seance", "-heure_debut")
        )
    else:
        sessions = (
            Seance.objects.filter(id_cours__professeur=request.user)
            .select_related("id_cours", "id_cours__id_departement")
            .order_by("-date_seance", "-heure_debut")
        )

    paginator = Paginator(sessions, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    sessions_by_course = defaultdict(list)
    for session in page_obj:
        sessions_by_course[session.id_cours].append(session)

    return render(
        request,
        "dashboard/instructor_sessions.html",
        {
            "academic_year": academic_year,
            "sessions": page_obj,
            "page_obj": page_obj,
            "sessions_by_course": dict(sessions_by_course),
        },
    )


@login_required
@professor_required
@require_GET
def instructor_statistics(request):
    """
    Page "Statistiques" — statistiques globales par cours pour le professeur.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    courses = Cours.objects.filter(professeur=request.user, actif=True)

    course_ids = list(courses.values_list("id_cours", flat=True))
    if academic_year:
        all_inscriptions = list(
            Inscription.objects.filter(
                id_cours__in=course_ids, id_annee=academic_year, status=Inscription.Status.EN_COURS
            ).select_related("id_cours")
        )
    else:
        all_inscriptions = list(
            Inscription.objects.filter(
                id_cours__in=course_ids, status=Inscription.Status.EN_COURS
            ).select_related("id_cours")
        )

    inscription_ids = [ins.id_inscription for ins in all_inscriptions]
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
    absence_counts = dict(
        Absence.objects.filter(id_inscription__in=inscription_ids)
        .values("id_inscription")
        .annotate(total=Count("id_absence"))
        .values_list("id_inscription", "total")
    )

    inscriptions_by_course = defaultdict(list)
    for ins in all_inscriptions:
        inscriptions_by_course[ins.id_cours_id].append(ins)

    course_stats = []
    total_students = 0
    total_at_risk = 0
    total_absences = 0

    for course in courses:
        inscriptions = inscriptions_by_course.get(course.id_cours, [])
        course_at_risk = 0
        course_absences = 0
        rates = []

        for ins in inscriptions:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (
                (total_abs / course.nombre_total_periodes) * 100
                if course.nombre_total_periodes > 0
                else 0.0
            )
            rates.append(rate)
            course_absences += absence_counts.get(ins.id_inscription, 0) or 0
            seuil = course.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                course_at_risk += 1

        course_avg_rate = sum(rates) / len(rates) if rates else 0

        course_stats.append(
            {
                "course": course,
                "students_count": len(inscriptions),
                "at_risk_count": course_at_risk,
                "absences_count": course_absences,
                "avg_rate": round(course_avg_rate, 1),
            }
        )

        total_students += len(inscriptions)
        total_at_risk += course_at_risk
        total_absences += course_absences

    overall_at_risk_rate = (total_at_risk / total_students * 100) if total_students > 0 else 0

    return render(
        request,
        "dashboard/instructor_statistics.html",
        {
            "academic_year": academic_year,
            "course_stats": course_stats,
            "total_students": total_students,
            "total_at_risk": total_at_risk,
            "total_absences": total_absences,
            "overall_at_risk_rate": round(overall_at_risk_rate, 1),
        },
    )
