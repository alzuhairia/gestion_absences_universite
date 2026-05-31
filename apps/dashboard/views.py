"""
Hub des vues du tableau de bord et point d'entrée de répartition par rôle pour UniAbsences.

Ce module a deux objectifs :

1. **Répartition par rôle** — ``dashboard_index`` redirige l'utilisateur
   authentifié vers le tableau de bord spécifique à son rôle (admin,
   secrétariat, professeur, étudiant).

2. **Hub de réexportation** — réexporte les symboles de vues publiques
   des sous-modules secrétariat, étudiant et professeur afin que
   ``urls.py`` puisse importer depuis ``dashboard.views`` sans
   connaître l'organisation interne des sous-modules.

Fait partie du système de tableau de bord UniAbsences.
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
    Redirige l'utilisateur authentifié vers son tableau de bord spécifique au rôle.

    Inspecte ``request.user.role`` et délègue à la fonction de vue
    appropriée selon le rôle.  Si le rôle n'est pas reconnu,
    l'utilisateur est redirigé vers la page de connexion avec un
    message d'erreur.

    Parameters
    ----------
    request : HttpRequest
        La requête HTTP entrante.  L'utilisateur doit être authentifié
        (appliqué par ``@login_required``).

    Returns
    -------
    HttpResponse
        La réponse produite par la vue de tableau de bord déléguée
        selon le rôle, ou une redirection vers ``accounts:login`` pour
        les rôles non reconnus.
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
        return redirect("accounts:login")


@login_required
def admin_dashboard(request):
    """
    Point d'entrée de l'URL ``/dashboard/admin/``.

    Distribue vers le gestionnaire approprié selon le rôle de l'appelant :

    - **ADMIN** — délègue à ``admin_dashboard_main`` (tableau de bord KPI complet).
    - **SECRETAIRE** — affiche l'index du secrétariat avec la liste
      des demandes de justification en attente (les secrétaires
      peuvent atteindre cette URL en navigant depuis leur propre
      contexte ; ils voient une vue limitée plutôt que le tableau de
      bord admin complet).
    - **Tout autre rôle** — redirige vers ``dashboard:index`` avec une erreur.

    Parameters
    ----------
    request : HttpRequest
        La requête HTTP entrante.

    Returns
    -------
    HttpResponse
        La réponse déléguée du tableau de bord admin, la vue partielle
        du secrétariat, ou une redirection en cas d'échec d'autorisation.
    """
    if request.user.role == User.Role.ADMIN:
        from .views_admin import admin_dashboard_main

        return admin_dashboard_main(request)
    elif request.user.role == User.Role.SECRETAIRE:
        # Les secrétaires atteignent légitimement cette URL ; affichez-leur les tâches en attente.
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
