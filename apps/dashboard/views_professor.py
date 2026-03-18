from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold, predict_absence_risk
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours
from apps.dashboard.decorators import professor_required
from apps.enrollments.models import Inscription


@login_required
@professor_required
@require_GET
def instructor_dashboard(request):
    """
    Vue du tableau de bord professeur - Pédagogique uniquement
    Affiche les KPIs, cours actifs, et informations pédagogiques.
    STRICT: Aucune action administrative permise.
    """

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    from django.utils import timezone

    today = timezone.now().date()

    # --- KPI 1: Active Courses (assigned to professor, marked as active)
    active_courses = Cours.objects.filter(professeur=request.user, actif=True)
    active_courses_count = active_courses.count()

    # --- KPI 2: Sessions Given (current year, past sessions)
    if academic_year:
        sessions_given = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__lt=today,
        ).count()
    else:
        sessions_given = 0

    # --- KPI 3: Upcoming Sessions (current year, future sessions)
    if academic_year:
        upcoming_sessions = Seance.objects.filter(
            id_cours__professeur=request.user,
            id_annee=academic_year,
            date_seance__gte=today,
        ).count()
    else:
        upcoming_sessions = 0

    # --- KPI 4: Total Recorded Absences (current year, in professor's courses)
    if academic_year:
        total_absences = Absence.objects.filter(
            id_seance__id_cours__professeur=request.user,
            id_seance__id_annee=academic_year,
        ).count()
    else:
        total_absences = 0

    # --- KPI 5: Students At Risk - READ ONLY, INDICATIVE ONLY
    all_inscriptions = Inscription.objects.filter(
        id_cours__professeur=request.user
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions = all_inscriptions.filter(id_annee=academic_year)

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
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
            # Calculate NON_JUSTIFIED absences only
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)

            rate = (total_abs / cours.nombre_total_periodes) * 100

            seuil = cours.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            if rate >= seuil_effectif:
                # Bloqué (même si exempté, le seuil effectif est dépassé)
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
                # Sous exemption (entre seuil normal et seuil effectif)
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
            "at_risk_list": at_risk_list[:5],  # Limit to 5 for dashboard display
        },
    )


@login_required
@professor_required
@require_GET
def instructor_course_detail(request, course_id):
    """
    Page de détails du cours pour le professeur - Lecture seule pour les étudiants, gestion des séances pour le professeur.
    STRICT: Aucune action administrative permise.
    """
    # Get course and verify it belongs to the instructor
    course = get_object_or_404(Cours, id_cours=course_id)
    if course.professeur_id != request.user.pk:
        messages.error(request, "Accès non autorisé à ce cours.")
        return redirect("dashboard:instructor_dashboard")

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get active tab
    active_tab = request.GET.get("tab", "students")

    # Tab 1: Students (READ ONLY)
    students_data = []
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_cours=course, id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant")
    else:
        inscriptions = Inscription.objects.filter(
            id_cours=course, status=Inscription.Status.EN_COURS
        ).select_related("id_etudiant")

    # Evaluate once: extract IDs from Python objects instead of an extra query.
    inscriptions = list(inscriptions)
    inscription_ids = [ins.id_inscription for ins in inscriptions]
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    system_threshold = get_system_threshold()
    course_threshold = (
        course.seuil_absence if course.seuil_absence is not None else system_threshold
    )

    for ins in inscriptions:
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        rate = (
            (total_abs / course.nombre_total_periodes) * 100
            if course.nombre_total_periodes > 0
            else 0.0
        )
        seuil_effectif = min(course_threshold + ins.exemption_margin, 100) if ins.exemption_40 else course_threshold
        is_at_risk = rate >= course_threshold
        is_blocked = rate >= seuil_effectif
        is_under_exemption = ins.exemption_40 and is_at_risk and not is_blocked

        students_data.append(
            {
                "inscription": ins,
                "etudiant": ins.id_etudiant,
                "total_abs": total_abs,
                "rate": round(rate, 1),
                "is_at_risk": is_at_risk,
                "is_blocked": is_blocked,
                "is_exempted": ins.exemption_40,
                "is_under_exemption": is_under_exemption,
                "seuil_effectif": seuil_effectif,
            }
        )

    # Predictive absence detection — enrich students_data with risk projections
    predictions = predict_absence_risk(
        inscriptions, academic_year=academic_year, system_threshold=system_threshold
    )
    predictions_by_id = {p["inscription"].id_inscription: p for p in predictions}
    early_warnings_count = 0
    for sd in students_data:
        pred = predictions_by_id.get(sd["inscription"].id_inscription)
        if pred:
            sd["risk_level"] = pred["risk_level"]
            sd["projected_rate"] = pred["projected_rate"]
            sd["recent_rate"] = pred["recent_rate"]
            sd["course_avg_rate"] = pred["course_avg_rate"]
            sd["days_remaining"] = pred["days_remaining"]
            sd["trend"] = pred["trend"]
            if pred["risk_level"] in ("HIGH", "MEDIUM") and not sd["is_at_risk"]:
                early_warnings_count += 1
        else:
            sd["risk_level"] = "NONE"
            sd["projected_rate"] = sd["rate"]
            sd["recent_rate"] = 0
            sd["course_avg_rate"] = 0
            sd["days_remaining"] = 0
            sd["trend"] = "stable"

    # Tab 2: Sessions
    if academic_year:
        sessions = Seance.objects.filter(
            id_cours=course, id_annee=academic_year
        ).order_by("-date_seance", "-heure_debut")
    else:
        sessions = Seance.objects.filter(id_cours=course).order_by(
            "-date_seance", "-heure_debut"
        )

    # Tab 3: Statistics
    total_students = len(students_data)
    at_risk_students = sum(1 for s in students_data if s["is_at_risk"])
    total_absences_all = Absence.objects.filter(id_seance__id_cours=course)
    if academic_year:
        total_absences_all = total_absences_all.filter(
            id_seance__id_annee=academic_year
        )
    total_absences_all = total_absences_all.count()

    # Overall absence rate (average)
    if total_students > 0:
        overall_rate = sum(s["rate"] for s in students_data) / total_students
    else:
        overall_rate = 0

    return render(
        request,
        "dashboard/instructor_course_detail.html",
        {
            "course": course,
            "academic_year": academic_year,
            "active_tab": active_tab,
            "students_data": students_data,
            "sessions": sessions,
            "total_students": total_students,
            "at_risk_students": at_risk_students,
            "total_absences_all": total_absences_all,
            "overall_rate": round(overall_rate, 1),
            "early_warnings_count": early_warnings_count,
            "course_threshold": course_threshold,
        },
    )


@login_required
@professor_required
@require_GET
def instructor_courses(request):
    """
    Page "Mes Cours" - Liste de tous les cours assignés au professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get all active courses assigned to professor
    courses = (
        Cours.objects.filter(professeur=request.user, actif=True)
        .select_related("id_departement", "id_departement__id_faculte")
        .order_by("code_cours")
    )

    # Prepare course data with statistics
    courses_data = []
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
            Inscription.objects.filter(id_cours__in=course_ids)
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
        all_course_inscriptions = all_course_inscriptions.filter(
            id_annee=academic_year
        )
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=all_course_inscriptions.values_list(
                "id_inscription", flat=True
            ),
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    inscriptions_by_course = defaultdict(list)
    for ins in all_course_inscriptions:
        inscriptions_by_course[ins.id_cours_id].append(ins)

    for course in courses:
        enrolled_count = enrolled_counts.get(course.id_cours, 0)
        sessions_count = sessions_counts.get(course.id_cours, 0)

        # Calculate at-risk students count
        inscriptions = inscriptions_by_course.get(course.id_cours, [])
        at_risk = 0
        for ins in inscriptions:
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
        {
            "academic_year": academic_year,
            "courses_data": courses_data,
        },
    )


@login_required
@professor_required
@require_GET
def instructor_sessions(request):
    """
    Page "Séances" - Liste de toutes les séances du professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get all sessions for professor's courses
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

    # Pagination
    paginator = Paginator(sessions, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Group paginated sessions by course
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
    Page "Statistiques" - Statistiques globales pour le professeur.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get all active courses
    courses = Cours.objects.filter(professeur=request.user, actif=True)

    # Statistics by course
    course_stats = []
    total_students = 0
    total_at_risk = 0
    total_absences = 0

    course_ids = list(courses.values_list("id_cours", flat=True))
    if academic_year:
        all_inscriptions = Inscription.objects.filter(
            id_cours__in=course_ids, id_annee=academic_year, status=Inscription.Status.EN_COURS
        )
    else:
        all_inscriptions = Inscription.objects.filter(
            id_cours__in=course_ids, status=Inscription.Status.EN_COURS
        )

    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
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
    for ins in all_inscriptions.select_related("id_cours"):
        inscriptions_by_course[ins.id_cours_id].append(ins)

    for course in courses:
        inscriptions = inscriptions_by_course.get(course.id_cours, [])
        course_at_risk = 0
        course_absences = 0
        course_avg_rate = 0

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

        if rates:
            course_avg_rate = sum(rates) / len(rates)

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

    # Overall statistics
    overall_at_risk_rate = (
        (total_at_risk / total_students * 100) if total_students > 0 else 0
    )

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
