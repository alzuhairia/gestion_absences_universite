"""
FICHIER : apps/accounts/views_profile.py
RESPONSABILITE : Profil utilisateur et téléchargement du rapport PDF étudiant
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from apps.absences.models import Absence
from apps.absences.utils import generate_absence_report
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@require_GET
def profile_view(request):
    """
    Vue de profil qui utilise le bon template selon le rôle de l'utilisateur.

    Centralise tout ce qui est lié au compte utilisateur :
      - Informations personnelles (lecture seule)
      - Sécurité : mot de passe + 2FA (boutons vers les vues dédiées)
    """
    user = request.user

    context = {
        "user": user,
        "two_factor_enabled": bool(getattr(user, "two_factor_enabled", False)),
    }

    if user.role == user.Role.ADMIN:
        template = "accounts/profile_admin.html"
    elif user.role == user.Role.SECRETAIRE:
        template = "accounts/profile_secretary.html"
    elif user.role == user.Role.PROFESSEUR:
        template = "accounts/profile_instructor.html"
    else:
        template = "accounts/profile_student.html"

    return render(request, template, context)


@login_required
@require_GET
def download_report_pdf(request):
    """
    Génère et télécharge le rapport PDF des absences.
    Réservé aux étudiants — chaque étudiant ne peut télécharger que son propre relevé.
    """
    from apps.absences.services import get_system_threshold
    from apps.accounts.models import User
    from apps.academic_sessions.models import AnneeAcademique

    user = request.user
    if user.role != User.Role.ETUDIANT:
        messages.error(request, "Accès réservé aux étudiants.")
        return redirect("dashboard:index")

    system_threshold = get_system_threshold()

    active_year = AnneeAcademique.objects.filter(active=True).first()
    if not active_year:
        active_year = AnneeAcademique.objects.order_by("-id_annee").first()

    inscriptions = Inscription.objects.filter(
        id_etudiant=user, status=Inscription.Status.EN_COURS
    ).select_related("id_cours", "id_annee")
    if active_year:
        inscriptions = inscriptions.filter(id_annee=active_year)

    cours_data = []
    academic_year = active_year.libelle if active_year else "N/A"

    for ins in inscriptions:
        total_abs = (
            Absence.objects.filter(
                id_inscription=ins,
                statut__in=[Absence.Statut.NON_JUSTIFIEE, Absence.Statut.EN_ATTENTE],
            ).aggregate(total=Sum("duree_absence"))["total"]
            or 0
        )

        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0
        seuil = (
            cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        )
        absence_rate = (total_abs / total_periodes) * 100 if total_periodes > 0 else 0
        is_eligible = absence_rate < seuil

        cours_data.append(
            {
                "nom": cours.nom_cours,
                "total_periods": total_periodes,
                "duree_absence": total_abs,
                "absence_rate": absence_rate,
                "status": is_eligible,
            }
        )

    response = HttpResponse(content_type="application/pdf")
    filename_safe = "".join(
        c if c.isalnum() or c in "._-" else "_"
        for c in f"{user.prenom}_{user.nom}"
    )
    response["Content-Disposition"] = (
        f'attachment; filename="releve_absences_{filename_safe}.pdf"'
    )

    generate_absence_report(response, user, academic_year, cours_data)

    return response
