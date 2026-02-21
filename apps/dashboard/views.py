from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Min, Q, Sum
from django.shortcuts import redirect, render

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.dashboard import views_professor, views_student
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


@login_required
def dashboard_redirect(request):
    """
    Redirige l'utilisateur vers le bon dashboard en fonction de son rôle.
    """
    user = request.user
    if user.role == User.Role.ETUDIANT:
        return student_dashboard(request)
    elif user.role == User.Role.PROFESSEUR:
        return instructor_dashboard(request)
    elif user.role == User.Role.ADMIN:
        return admin_dashboard(request)
    elif user.role == User.Role.SECRETAIRE:
        return secretary_dashboard(request)
    else:
        # Fallback ou message d'erreur
        messages.error(request, "Rôle non reconnu ou accès non autorisé.")
        return render(request, "dashboard/error.html")


@login_required
def admin_dashboard(request):
    """
    Vue tableau de bord admin - Redirige vers le dashboard complet.
    IMPORTANT: L'ancien dashboard (admin_index.html) avec les justificatifs
    n'est plus accessible aux administrateurs - c'est une tâche opérationnelle.
    """
    if request.user.role == User.Role.ADMIN:
        from .views_admin import admin_dashboard_main

        return admin_dashboard_main(request)
    elif request.user.role == User.Role.SECRETAIRE:
        # Le secrétariat peut voir les justificatifs en attente
        pending_justifications = Justification.objects.filter(
            state="EN_ATTENTE"
        ).select_related("id_absence__id_inscription__id_etudiant")
        return render(
            request,
            "dashboard/secretary_index.html",
            {"pending_justifications": pending_justifications},
        )
    else:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:index")


@login_required
@secretary_required
def secretary_dashboard(request):
    """
    Vue tableau de bord secrétaire - KPIs uniquement
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # 1. Pending Justifications Count
    global_pending_count = Justification.objects.filter(state="EN_ATTENTE").count()

    # 2. Global "At Risk" Calculation (> 40%)
    all_inscriptions = Inscription.objects.select_related(
        "id_cours", "id_etudiant"
    ).all()
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    global_at_risk_count = 0

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = absence_sums.get(ins.id_inscription, 0) or 0

            rate = (total_abs / cours.nombre_total_periodes) * 100

            # CORRECTION BUG CRITIQUE #4d — seuil configuré par cours
            seuil = cours.get_seuil_absence()
            if rate >= seuil and not ins.exemption_40:
                global_at_risk_count += 1

    # 5. KPI Calculations
    # Active Inscriptions (Inscriptions in the current academic year)
    active_inscriptions_count = 0
    if academic_year:
        active_inscriptions_count = Inscription.objects.filter(
            id_annee=academic_year, status="EN_COURS"
        ).count()

    # Active Courses: Use shared function to ensure consistency with active_courses view
    # Business Rule: Courses with assigned professor AND (sessions OR enrollments) in current year
    active_courses_queryset = get_active_courses_queryset(academic_year)
    active_courses_count = active_courses_queryset.count()

    return render(
        request,
        "dashboard/secretary_index.html",
        {
            "global_pending_count": global_pending_count,
            "global_at_risk_count": global_at_risk_count,
            "academic_year": academic_year,
            "active_inscriptions_count": active_inscriptions_count,
            "active_courses_count": active_courses_count,
        },
    )


@login_required
@secretary_required
def secretary_enrollments(request):
    """
    Page "Inscriptions" - Gestion des inscriptions étudiantes.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get all inscriptions for current year
    if academic_year:
        inscriptions = Inscription.objects.filter(
            id_annee=academic_year, status="EN_COURS"
        ).select_related(
            "id_etudiant",
            "id_cours",
            "id_cours__id_departement",
            "id_cours__id_departement__id_faculte",
        )
    else:
        inscriptions = Inscription.objects.filter(status="EN_COURS").select_related(
            "id_etudiant",
            "id_cours",
            "id_cours__id_departement",
            "id_cours__id_departement__id_faculte",
        )

    # Get filter parameters
    faculty_filter = request.GET.get("faculty", "")
    department_filter = request.GET.get("department", "")
    course_filter = request.GET.get("course", "")
    search_query = request.GET.get("q", "")

    # Apply filters
    if faculty_filter:
        inscriptions = inscriptions.filter(
            id_cours__id_departement__id_faculte_id=faculty_filter
        )
    if department_filter:
        inscriptions = inscriptions.filter(
            id_cours__id_departement_id=department_filter
        )
    if course_filter:
        inscriptions = inscriptions.filter(id_cours_id=course_filter)
    if search_query:
        inscriptions = inscriptions.filter(
            Q(id_etudiant__nom__icontains=search_query)
            | Q(id_etudiant__prenom__icontains=search_query)
            | Q(id_etudiant__email__icontains=search_query)
            | Q(id_cours__code_cours__icontains=search_query)
            | Q(id_cours__nom_cours__icontains=search_query)
        )

    # Regrouper les inscriptions par étudiant
    students_enrollments = defaultdict(list)

    for inscription in inscriptions.order_by(
        "id_etudiant__nom", "id_etudiant__prenom", "id_cours__code_cours"
    ):
        students_enrollments[inscription.id_etudiant].append(inscription)

    # Créer une liste de tuples (étudiant, liste_des_inscriptions) pour la pagination
    students_list = list(students_enrollments.items())

    # Pagination
    from django.core.paginator import Paginator

    paginator = Paginator(students_list, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Get filter options
    faculties = Faculte.objects.filter(actif=True).order_by("nom_faculte")
    departments = Departement.objects.filter(actif=True).order_by("nom_departement")
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    courses = Cours.objects.filter(actif=True).order_by("code_cours")
    if department_filter:
        courses = courses.filter(id_departement_id=department_filter)

    return render(
        request,
        "dashboard/secretary_enrollments.html",
        {
            "academic_year": academic_year,
            "page_obj": page_obj,
            "faculties": faculties,
            "departments": departments,
            "courses": courses,
            "faculty_filter": faculty_filter,
            "department_filter": department_filter,
            "course_filter": course_filter,
            "search_query": search_query,
        },
    )


@login_required
@secretary_required
def secretary_rules_40(request):
    """
    Page "Règle des 40%" - Gestion des exemptions et étudiants à risque.
    """
    # Get all inscriptions
    all_inscriptions = Inscription.objects.select_related(
        "id_cours", "id_etudiant", "id_cours__id_departement"
    ).all()
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    at_risk_list = []

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = absence_sums.get(ins.id_inscription, 0) or 0

            rate = (total_abs / cours.nombre_total_periodes) * 100

            # CORRECTION BUG CRITIQUE #4e — seuil configuré par cours
            seuil = cours.get_seuil_absence()
            # Afficher si taux >= seuil OU si exempté (pour pouvoir révoquer si besoin)
            if rate >= seuil:
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "is_blocked": not ins.exemption_40,
                        "exemption": ins.exemption_40,
                        "motif_exemption": ins.motif_exemption,
                    }
                )

    # Calculate statistics
    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = len(at_risk_list) - blocked_count

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    return render(
        request,
        "dashboard/secretary_rules_40.html",
        {
            "academic_year": academic_year,
            "at_risk_list": at_risk_list,
            "blocked_count": blocked_count,
            "exempted_count": exempted_count,
        },
    )


@login_required
@secretary_required
def secretary_exports(request):
    """
    Page "Exports" - Téléchargement des rapports Excel/PDF.
    """
    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Calculate statistics for display
    if academic_year:
        active_inscriptions = Inscription.objects.filter(
            id_annee=academic_year,
            status="EN_COURS",
        ).select_related("id_cours")
    else:
        active_inscriptions = Inscription.objects.filter(
            status="EN_COURS"
        ).select_related("id_cours")

    active_inscriptions_list = list(active_inscriptions)
    inscription_ids = [ins.id_inscription for ins in active_inscriptions_list]
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            # CORRECTION BUG CRITIQUE #3b — EN_ATTENTE compte comme NON_JUSTIFIEE (loophole fermé)
            statut__in=["NON_JUSTIFIEE", "EN_ATTENTE"],
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Count at-risk students
    at_risk_count = 0
    for ins in active_inscriptions_list:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = absence_sums.get(ins.id_inscription, 0) or 0
            rate = (total_abs / cours.nombre_total_periodes) * 100
            # CORRECTION BUG CRITIQUE #4f — seuil configuré par cours
            seuil = ins.id_cours.get_seuil_absence()
            if rate >= seuil and not ins.exemption_40:
                at_risk_count += 1

    return render(
        request,
        "dashboard/secretary_exports.html",
        {
            "academic_year": academic_year,
            "active_inscriptions_count": len(active_inscriptions_list),
            "at_risk_count": at_risk_count,
        },
    )


def get_active_courses_queryset(academic_year):
    """
    Shared function to get active courses based on business rule.

    Business Rule: Active Courses = Courses that:
    1. Have an assigned professor (professeur__isnull=False)
    2. AND have sessions OR enrollments (or both) in the current academic year

    This ensures consistency between KPI calculation and the active courses list.

    Returns: QuerySet of Cours objects
    """
    courses = Cours.objects.filter(professeur__isnull=False)

    if not academic_year:
        return courses.none()

    courses_with_sessions = Seance.objects.filter(id_annee=academic_year).values(
        "id_cours"
    )
    courses_with_enrollments = Inscription.objects.filter(
        id_annee=academic_year
    ).values("id_cours")

    # Semi-join style filtering avoids correlated subqueries per row.
    return courses.filter(
        Q(id_cours__in=courses_with_sessions) | Q(id_cours__in=courses_with_enrollments)
    )


@login_required
def active_courses(request):
    """
    View to display active courses for the current academic year.
    Administrative view - read-only for secretary.
    """
    if (
        request.user.role != User.Role.SECRETAIRE
        and request.user.role != User.Role.ADMIN
    ):
        return redirect("dashboard:index")

    # Get current academic year
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    # Get filter parameters
    faculty_filter = request.GET.get("faculty", "")
    department_filter = request.GET.get("department", "")
    professor_filter = request.GET.get("professor", "")
    search_query = request.GET.get("q", "")

    # Use shared function to get active courses (ensures consistency with KPI)
    # Business Rule: Courses with assigned professor AND (sessions OR enrollments) in current year
    courses = get_active_courses_queryset(academic_year).select_related(
        "professeur", "id_departement", "id_departement__id_faculte"
    )

    # Apply filters
    if faculty_filter:
        courses = courses.filter(id_departement__id_faculte_id=faculty_filter)

    if department_filter:
        courses = courses.filter(id_departement_id=department_filter)

    if professor_filter:
        courses = courses.filter(professeur_id=professor_filter)

    if search_query:
        courses = courses.filter(
            Q(code_cours__icontains=search_query) | Q(nom_cours__icontains=search_query)
        )

    # Order by course code
    courses = courses.order_by("code_cours")

    # Evaluate filtered courses first, then aggregate only on relevant IDs.
    courses = list(courses)
    course_ids = [course.id_cours for course in courses]

    enrolled_counts = {}
    session_bounds = {}
    courses_with_sessions = set()
    if course_ids:
        enrollments_qs = Inscription.objects.filter(id_cours__in=course_ids)
        sessions_qs = Seance.objects.filter(id_cours__in=course_ids)

        if academic_year:
            enrollments_qs = enrollments_qs.filter(
                id_annee=academic_year,
                status="EN_COURS",
            )
            sessions_qs = sessions_qs.filter(id_annee=academic_year)

        enrolled_counts = dict(
            enrollments_qs.values("id_cours")
            .annotate(total=Count("id_inscription"))
            .values_list("id_cours", "total")
        )
        session_bounds = {
            row["id_cours"]: row
            for row in sessions_qs.values("id_cours").annotate(
                first_session_date=Min("date_seance"),
                last_session_date=Max("date_seance"),
            )
        }
        courses_with_sessions = set(session_bounds.keys())

    # Get filter options
    faculties = Faculte.objects.all().order_by("nom_faculte")
    departments = Departement.objects.all().order_by("nom_departement")
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    professors = User.objects.filter(role=User.Role.PROFESSEUR).order_by(
        "nom", "prenom"
    )

    # Prepare course data with additional info (no per-course SQL)
    courses_data = []
    for course in courses:
        # Determine semester/period from pre-aggregated bounds
        semester_info = "N/A"
        bounds = session_bounds.get(course.id_cours)
        first_session_date = bounds["first_session_date"] if bounds else None
        last_session_date = bounds["last_session_date"] if bounds else None
        if first_session_date and last_session_date:
            months = (last_session_date.year - first_session_date.year) * 12 + (
                last_session_date.month - first_session_date.month
            )
            if months > 3:
                semester_info = (
                    f"Semestre complet ({first_session_date.strftime('%m/%Y')} - "
                    f"{last_session_date.strftime('%m/%Y')})"
                )
            else:
                semester_info = f"{first_session_date.strftime('%B %Y')}"

        courses_data.append(
            {
                "course": course,
                "enrolled_count": enrolled_counts.get(course.id_cours, 0),
                "semester_info": semester_info,
                "has_sessions": course.id_cours in courses_with_sessions,
            }
        )

    return render(
        request,
        "dashboard/active_courses.html",
        {
            "courses_data": courses_data,
            "academic_year": academic_year,
            "faculties": faculties,
            "departments": departments,
            "professors": professors,
            "current_faculty": faculty_filter,
            "current_department": department_filter,
            "current_professor": professor_filter,
            "search_query": search_query,
        },
    )


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility with urls.py
# (URLs reference views.student_dashboard, views.instructor_dashboard, etc.)
# ---------------------------------------------------------------------------
student_dashboard = views_student.student_dashboard
student_statistics = views_student.student_statistics
student_course_detail = views_student.student_course_detail
student_courses = views_student.student_courses
student_absences = views_student.student_absences
student_reports = views_student.student_reports

instructor_dashboard = views_professor.instructor_dashboard
instructor_course_detail = views_professor.instructor_course_detail
instructor_courses = views_professor.instructor_courses
instructor_sessions = views_professor.instructor_sessions
instructor_statistics = views_professor.instructor_statistics
