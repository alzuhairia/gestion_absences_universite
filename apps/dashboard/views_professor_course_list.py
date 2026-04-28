"""
Liste des cours assignés au professeur.

Fonctionnalités :
  - Liste de tous les cours actifs avec statistiques (inscrits, séances, à risque)
  - Filtré sur l'année académique active
"""

from collections import defaultdict

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
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
def instructor_courses(request):
    """
    Page "Mes Cours" — liste de tous les cours assignés au professeur avec statistiques.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    courses = (
        Cours.objects.filter(professeur=request.user, actif=True)
        .select_related("id_departement", "id_departement__id_faculte")
        .order_by("code_cours")
    )

    course_ids = list(courses.values_list("id_cours", flat=True))

    if academic_year:
        enrolled_counts = dict(
            Inscription.objects.filter(
                id_cours__in=course_ids, id_annee=academic_year, status=Inscription.Status.EN_COURS
            )
            .values("id_cours")
            .annotate(total=Count("id_inscription"))
            .values_list("id_cours", "total")
        )
        sessions_counts = dict(
            Seance.objects.filter(id_cours__in=course_ids, id_annee=academic_year)
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )
    else:
        enrolled_counts = dict(
            Inscription.objects.filter(
                id_cours__in=course_ids, status=Inscription.Status.EN_COURS
            )
            .values("id_cours")
            .annotate(total=Count("id_inscription"))
            .values_list("id_cours", "total")
        )
        sessions_counts = dict(
            Seance.objects.filter(id_cours__in=course_ids)
            .values("id_cours")
            .annotate(total=Count("id_seance"))
            .values_list("id_cours", "total")
        )

    all_course_inscriptions = Inscription.objects.filter(
        id_cours__in=course_ids, status=Inscription.Status.EN_COURS
    )
    if academic_year:
        all_course_inscriptions = all_course_inscriptions.filter(id_annee=academic_year)

    today = timezone.localdate()
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=all_course_inscriptions.values_list("id_inscription", flat=True),
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    inscriptions_by_course = defaultdict(list)
    for ins in all_course_inscriptions:
        inscriptions_by_course[ins.id_cours_id].append(ins)

    courses_data = []
    for course in courses:
        enrolled_count = enrolled_counts.get(course.id_cours, 0)
        sessions_count = sessions_counts.get(course.id_cours, 0)

        at_risk = 0
        for ins in inscriptions_by_course.get(course.id_cours, []):
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (
                (total_abs / course.nombre_total_periodes) * 100
                if course.nombre_total_periodes > 0
                else 0.0
            )
            seuil = course.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk += 1

        courses_data.append(
            {
                "course": course,
                "enrolled_count": enrolled_count,
                "sessions_count": sessions_count,
                "at_risk_count": at_risk,
            }
        )

    return render(
        request,
        "dashboard/instructor_courses.html",
        {"academic_year": academic_year, "courses_data": courses_data},
    )
