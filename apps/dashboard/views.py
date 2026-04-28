"""
FICHIER : apps/dashboard/views.py
RESPONSABILITE : Redirection par rôle + re-exports pour backward compatibility avec urls.py.

Les vues métier du secrétariat ont été extraites dans views_secretary_home.py.
Les vues étudiant / enseignant restent accessibles via leurs re-exports en bas de fichier.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from apps.absences.models import Justification
from apps.accounts.models import User
from apps.dashboard import views_professor, views_student

# Re-exports secrétariat — importés par urls.py via `from . import views`
from apps.dashboard.views_secretary_home import (  # noqa: F401
    active_courses,
    get_active_courses_queryset,
    secretary_dashboard,
    secretary_enrollments,
    secretary_exports,
    secretary_seuils_absence,
)


# ---------------------------------------------------------------------------
# Redirection par rôle
# ---------------------------------------------------------------------------


@login_required
def dashboard_redirect(request):
    """
    Redirige l'utilisateur vers le bon dashboard selon son rôle.
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
        messages.error(request, "Rôle non reconnu ou accès non autorisé.")
        return render(request, "dashboard/error.html")


@login_required
def admin_dashboard(request):
    """
    Redirige l'admin vers son dashboard complet ; affiche les justificatifs en attente
    pour le secrétariat (rôle secondaire autorisé).
    """
    if request.user.role == User.Role.ADMIN:
        from .views_admin import admin_dashboard_main

        return admin_dashboard_main(request)
    elif request.user.role == User.Role.SECRETAIRE:
        pending_justifications = Justification.objects.filter(
            state=Justification.State.EN_ATTENTE
        ).select_related("id_absence__id_inscription__id_etudiant")
        return render(
            request,
            "dashboard/secretary_index.html",
            {"pending_justifications": pending_justifications},
        )
    else:
        messages.error(request, "Accès non autorisé.")
        return redirect("dashboard:index")


# ---------------------------------------------------------------------------
# Re-exports étudiant / enseignant — backward compatibility avec urls.py
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
