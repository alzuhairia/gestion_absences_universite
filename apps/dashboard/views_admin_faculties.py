"""
Gestion CRUD des facultés (rôle administrateur).

Fonctionnalités :
  - Liste et création de facultés
  - Modification / désactivation
  - Suppression avec cascade (départements → cours → inscriptions → absences)
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.utils import safe_get_page
from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import Seance
from apps.academics.models import Cours, Departement, Faculte
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import FaculteForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculties(request):
    """Liste et création de facultés"""

    if request.method == "POST":
        form = FaculteForm(request.POST)
        if form.is_valid():
            faculte = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création de la faculté '{faculte.nom_faculte}' (Configuration système)",
                request,
                niveau="CRITIQUE",
                objet_type="FACULTE",
                objet_id=faculte.id_faculte,
            )
            messages.success(
                request, f"Faculté '{faculte.nom_faculte}' créée avec succès."
            )
            return redirect("dashboard:admin_faculties")
    else:
        form = FaculteForm()

    faculties = Faculte.objects.all().order_by("nom_faculte")
    paginator = Paginator(faculties, 20)
    faculties_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_faculties.html",
        {
            "faculties": faculties_page,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculty_edit(request, faculte_id):
    """Modification ou désactivation d'une faculté"""

    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)

    if request.method == "POST":
        form = FaculteForm(request.POST, instance=faculte)
        if form.is_valid():
            old_name = faculte.nom_faculte
            faculte = form.save()
            action = "modifiée" if faculte.actif else "désactivée"
            log_action(
                request.user,
                f"CRITIQUE: Faculté '{old_name}' {action} (Configuration système - {'Activation' if faculte.actif else 'Désactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="FACULTE",
                objet_id=faculte.id_faculte,
            )
            messages.success(
                request, f"Faculté '{faculte.nom_faculte}' {action} avec succès."
            )
            return redirect("dashboard:admin_faculties")
    else:
        form = FaculteForm(instance=faculte)

    return render(
        request,
        "dashboard/admin_faculty_edit.html",
        {
            "faculte": faculte,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculty_delete(request, faculte_id):
    """Suppression d'une faculté avec suppression en cascade des départements et cours"""

    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)
    faculte_nom = faculte.nom_faculte

    departements = Departement.objects.filter(id_faculte=faculte)
    departements_count = departements.count()
    cours = Cours.objects.filter(id_departement__in=departements)
    cours_count = cours.count()
    inscriptions = Inscription.objects.filter(id_cours__in=cours)
    inscriptions_count = inscriptions.count()
    absences = Absence.objects.filter(id_inscription__in=inscriptions)
    absences_count = absences.count()
    justifications = Justification.objects.filter(id_absence__in=absences)
    justifications_count = justifications.count()
    seances = Seance.objects.filter(id_cours__in=cours)
    seances_count = seances.count()

    if request.method == "GET":
        cascade_items = [
            item
            for item in [
                {"count": departements_count, "label": "département(s)"},
                {"count": cours_count, "label": "cours"},
                {"count": seances_count, "label": "séance(s)"},
                {"count": inscriptions_count, "label": "inscription(s)"},
                {"count": absences_count, "label": "absence(s)"},
                {"count": justifications_count, "label": "justification(s)"},
            ]
            if item["count"] > 0
        ]
        return render(
            request,
            "dashboard/admin_confirm_delete.html",
            {
                "object_label": f"Faculté « {faculte_nom} »",
                "cascade_items": cascade_items,
                "cancel_url": "/dashboard/admin/faculties/",
                "cancel_label": "Facultés",
            },
        )

    try:
        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()
            departements.delete()
            faculte.delete()

        cascade_info = []
        if departements_count > 0:
            cascade_info.append(f"{departements_count} département(s)")
        if cours_count > 0:
            cascade_info.append(f"{cours_count} cours")
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
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
            f"CRITIQUE: Suppression de la faculté '{faculte_nom}' (ID: {faculte_id}){cascade_msg} - Configuration système",
            request,
            niveau="CRITIQUE",
            objet_type="FACULTE",
            objet_id=faculte_id,
        )

        success_msg = f"Faculté '{faculte_nom}' supprimée avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)

    except ProtectedError as e:
        protected_objects = [str(obj) for obj in e.protected_objects]
        logger.error(f"ProtectedError lors de la suppression de la faculté {faculte_nom}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer la faculté '{faculte_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de la faculté {faculte_nom}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression de la faculté '{faculte_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_faculties")
