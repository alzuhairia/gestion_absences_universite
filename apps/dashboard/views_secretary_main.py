"""
FICHIER : apps/dashboard/views_secretary_main.py
RESPONSABILITE : Dashboard principal du secrétariat + vue cours actifs
"""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Min, Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription


def get_active_courses_queryset(academic_year):
    """
    Cours actifs = cours avec professeur assigné ET (séances OU inscriptions) dans l'année.
    Utilisée par le KPI du dashboard et par la vue active_courses pour rester cohérents.
    """
    courses = Cours.objects.filter(professeur__isnull=False, actif=True)

    if not academic_year:
        return courses.none()

    courses_with_sessions = Seance.objects.filter(id_annee=academic_year).values("id_cours")
    courses_with_enrollments = Inscription.objects.filter(
        id_annee=academic_year, status=Inscription.Status.EN_COURS
    ).values("id_cours")

    return courses.filter(
        Q(id_cours__in=courses_with_sessions) | Q(id_cours__in=courses_with_enrollments)
    )


@login_required
@secretary_required
@require_GET
def secretary_dashboard(request):
    """
    Dashboard secrétaire — KPIs absences, étudiants à risque, statistiques globales.
    """
    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    absence_base_qs = Absence.objects.all()
    if academic_year:
        absence_base_qs = absence_base_qs.filter(id_inscription__id_annee=academic_year)
    global_unjustified_count = absence_base_qs.filter(statut=Absence.Statut.NON_JUSTIFIEE).count()
    global_pending_count = absence_base_qs.filter(statut=Absence.Statut.EN_ATTENTE).count()

    all_inscriptions_qs = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_etudiant")
    if academic_year:
        all_inscriptions_qs = all_inscriptions_qs.filter(id_annee=academic_year)
    all_inscriptions = list(all_inscriptions_qs)
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

    global_at_risk_count = 0
    at_risk_list = []

    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
            rate = (total_abs / cours.nombre_total_periodes) * 100
            seuil = cours.get_seuil_absence()
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
            if rate >= seuil_effectif:
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "is_blocked": rate >= seuil_effectif,
                        "exemption": ins.exemption_40,
                    }
                )
                global_at_risk_count += 1

    at_risk_blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    at_risk_exempted_count = len(at_risk_list) - at_risk_blocked_count

    active_inscriptions_count = 0
    if academic_year:
        active_inscriptions_count = Inscription.objects.filter(
            id_annee=academic_year, status=Inscription.Status.EN_COURS
        ).count()

    active_courses_count = get_active_courses_queryset(academic_year).count()

    return render(
        request,
        "dashboard/secretary_index.html",
        {
            "global_unjustified_count": global_unjustified_count,
            "global_pending_count": global_pending_count,
            "global_at_risk_count": global_at_risk_count,
            "at_risk_list": at_risk_list,
            "at_risk_blocked_count": at_risk_blocked_count,
            "at_risk_exempted_count": at_risk_exempted_count,
            "academic_year": academic_year,
            "active_inscriptions_count": active_inscriptions_count,
            "active_courses_count": active_courses_count,
        },
    )


@login_required
@require_GET
def active_courses(request):
    """
    Vue des cours actifs pour l'année académique courante (admin + secrétaire).
    """
    if request.user.role not in (User.Role.SECRETAIRE, User.Role.ADMIN):
        return redirect("dashboard:index")

    academic_year = AnneeAcademique.objects.filter(active=True).first()
    if not academic_year:
        academic_year = AnneeAcademique.objects.order_by("-id_annee").first()

    faculty_filter = request.GET.get("faculty", "")
    department_filter = request.GET.get("department", "")
    professor_filter = request.GET.get("professor", "")
    search_query = request.GET.get("q", "")

    courses = get_active_courses_queryset(academic_year).select_related(
        "professeur", "id_departement", "id_departement__id_faculte"
    )

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

    courses = list(courses.order_by("code_cours"))
    course_ids = [course.id_cours for course in courses]

    enrolled_counts = {}
    session_bounds = {}
    courses_with_sessions = set()
    if course_ids:
        enrollments_qs = Inscription.objects.filter(
            id_cours__in=course_ids, status=Inscription.Status.EN_COURS
        )
        sessions_qs = Seance.objects.filter(id_cours__in=course_ids)
        if academic_year:
            enrollments_qs = enrollments_qs.filter(id_annee=academic_year)
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

    faculties = Faculte.objects.filter(actif=True).order_by("nom_faculte")
    departments = Departement.objects.filter(actif=True).order_by("nom_departement")
    if faculty_filter:
        departments = departments.filter(id_faculte_id=faculty_filter)
    professors = User.objects.filter(role=User.Role.PROFESSEUR).order_by("nom", "prenom")

    courses_data = []
    for course in courses:
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
