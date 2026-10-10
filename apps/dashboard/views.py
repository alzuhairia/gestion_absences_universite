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

# Re-exports étudiant / enseignant / secrétariat — importés par urls.py via `from . import views`.
# On utilise des `from X import Y` (plutôt que `Y = X.Y`) pour préserver l'info
# de type sur chaque vue : les stubs ``django-types`` exigent un `Callable` strict
# pour l'argument ``view`` de ``path(...)``, qu'une simple assignation ferait
# perdre.
from apps.dashboard.views_student import (  # noqa: F401
    student_absences,
    student_course_detail,
    student_courses,
    student_dashboard,
    student_reports,
    student_statistics,
)
from apps.dashboard.views_professor import (  # noqa: F401
    instructor_course_detail,
    instructor_courses,
    instructor_dashboard,
    instructor_sessions,
    instructor_statistics,
)
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


