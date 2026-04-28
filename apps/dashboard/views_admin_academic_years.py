"""
Gestion CRUD des années académiques (rôle administrateur).

Fonctionnalités :
  - Liste et création d'années académiques
  - Définir une année comme active (unique)
  - Suppression avec cascade (inscriptions → absences → séances)
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import AnneeAcademique, Seance
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import AnneeAcademiqueForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_academic_years(request):
    """Liste et gestion des années académiques"""

    if request.method == "POST":
        form = AnneeAcademiqueForm(request.POST)
        if form.is_valid():
            year = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création de l'année académique '{year.libelle}' (Configuration système - {'Année active' if year.active else 'Année inactive'})",
                request,
                niveau="CRITIQUE",
                objet_type="AUTRE",
                objet_id=year.id_annee,
            )
            messages.success(
                request, f"Année académique '{year.libelle}' créée avec succès."
            )
            return redirect("dashboard:admin_academic_years")
    else:
        form = AnneeAcademiqueForm()

    years = AnneeAcademique.objects.all().order_by("-libelle")

    return render(
        request,
        "dashboard/admin_academic_years.html",
        {
            "years": years,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_academic_year_set_active(request, year_id):
    """Définir une année académique comme active"""

    with transaction.atomic():
        year = get_object_or_404(
            AnneeAcademique.objects.select_for_update(), id_annee=year_id
        )
        year.active = True
        year.save()

        log_action(
            request.user,
            f"CRITIQUE: Année académique '{year.libelle}' définie comme active (Configuration système - Changement d'année académique)",
            request,
            niveau="CRITIQUE",
            objet_type="AUTRE",
            objet_id=year.id_annee,
        )
    messages.success(
        request, f"Année académique '{year.libelle}' définie comme active."
    )

    return redirect("dashboard:admin_academic_years")


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_academic_year_delete(request, year_id):
    """Suppression d'une année académique avec suppression en cascade"""

    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    year_libelle = year.libelle

    try:
        with transaction.atomic():
            year = AnneeAcademique.objects.select_for_update().get(id_annee=year_id)

            if year.active:
                messages.error(
                    request,
                    f"Impossible de supprimer l'annee academique '{year_libelle}' car elle est actuellement active. "
                    f"Veuillez d'abord definir une autre annee comme active.",
                )
                return redirect("dashboard:admin_academic_years")

            inscriptions = Inscription.objects.filter(id_annee=year)
            inscriptions_count = inscriptions.count()

            absences = Absence.objects.filter(id_inscription__in=inscriptions)
            absences_count = absences.count()

            justifications = Justification.objects.filter(id_absence__in=absences)
            justifications_count = justifications.count()

            seances = Seance.objects.filter(id_annee=year)
            seances_count = seances.count()

            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            year.delete()

        cascade_info = []
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} seance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")

        cascade_msg = (
            f" (suppression en cascade: {', '.join(cascade_info)})"
            if cascade_info
            else ""
        )

        log_action(
            request.user,
            f"CRITIQUE: Suppression de l'annee academique '{year_libelle}' (ID: {year_id}){cascade_msg} - Configuration systeme",
            request,
            niveau="CRITIQUE",
            objet_type="AUTRE",
            objet_id=year_id,
        )

        success_msg = f"Annee academique '{year_libelle}' supprimee avec succes."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuee : {', '.join(cascade_info)}."
        messages.success(request, success_msg)

    except ProtectedError as e:
        protected_objects = [str(obj) for obj in e.protected_objects]
        logger.error(f"ProtectedError lors de la suppression de l'annee academique {year_libelle}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer l'annee academique '{year_libelle}'. "
            f"Dependances trouvees : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces elements.",
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de l'annee academique {year_libelle}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression de l'annee academique '{year_libelle}'. "
            f"Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )

    return redirect("dashboard:admin_academic_years")
