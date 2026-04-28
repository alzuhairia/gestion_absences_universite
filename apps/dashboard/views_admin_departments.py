"""
Gestion CRUD des départements (rôle administrateur).

Fonctionnalités :
  - Liste et création de départements
  - Modification / désactivation
  - Suppression avec cascade (cours → inscriptions → absences)
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
from apps.academics.models import Cours, Departement
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import DepartementForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_departments(request):
    """Liste et création de départements"""

    if request.method == "POST":
        form = DepartementForm(request.POST)
        if form.is_valid():
            dept = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création du département '{dept.nom_departement}' dans la faculté '{dept.id_faculte.nom_faculte}' (Configuration système)",
                request,
                niveau="CRITIQUE",
                objet_type="DEPARTEMENT",
                objet_id=dept.id_departement,
            )
            messages.success(
                request, f"Département '{dept.nom_departement}' créé avec succès."
            )
            return redirect("dashboard:admin_departments")
    else:
        form = DepartementForm()

    departments = (
        Departement.objects.select_related("id_faculte")
        .all()
        .order_by("id_faculte__nom_faculte", "nom_departement")
    )
    paginator = Paginator(departments, 20)
    departments_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_departments.html",
        {
            "departments": departments_page,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_department_edit(request, dept_id):
    """Modification ou désactivation d'un département"""

    dept = get_object_or_404(Departement, id_departement=dept_id)

    if request.method == "POST":
        form = DepartementForm(request.POST, instance=dept)
        if form.is_valid():
            old_name = dept.nom_departement
            dept = form.save()
            action = "modifié" if dept.actif else "désactivé"
            log_action(
                request.user,
                f"CRITIQUE: Département '{old_name}' {action} (Configuration système - {'Activation' if dept.actif else 'Désactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="DEPARTEMENT",
                objet_id=dept.id_departement,
            )
            messages.success(
                request, f"Département '{dept.nom_departement}' {action} avec succès."
            )
            return redirect("dashboard:admin_departments")
    else:
        form = DepartementForm(instance=dept)

    return render(
        request,
        "dashboard/admin_department_edit.html",
        {
            "department": dept,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_department_delete(request, dept_id):
    """Suppression d'un département avec suppression en cascade des cours"""

    dept = get_object_or_404(Departement, id_departement=dept_id)
    dept_nom = dept.nom_departement
    faculte_nom = dept.id_faculte.nom_faculte

    cours = Cours.objects.filter(id_departement=dept)
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
                "object_label": f"Département « {dept_nom} » (Faculté : {faculte_nom})",
                "cascade_items": cascade_items,
                "cancel_url": "/dashboard/admin/departments/",
                "cancel_label": "Départements",
            },
        )

    try:
        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()
            dept.delete()

        cascade_info = []
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
            f"CRITIQUE: Suppression du département '{dept_nom}' (Faculté: {faculte_nom}, ID: {dept_id}){cascade_msg} - Configuration système",
            request,
            niveau="CRITIQUE",
            objet_type="DEPARTEMENT",
            objet_id=dept_id,
        )

        success_msg = f"Département '{dept_nom}' supprimé avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)

    except ProtectedError as e:
        protected_objects = [str(obj) for obj in e.protected_objects]
        logger.error(f"ProtectedError lors de la suppression du département {dept_nom}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer le département '{dept_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression du département {dept_nom}: {e}", exc_info=True)
        messages.error(
            request,
            f"Erreur lors de la suppression du département '{dept_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_departments")
