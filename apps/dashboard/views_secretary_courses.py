"""
Gestion CRUD des cours (rôle secrétaire).

Fonctionnalités :
  - Liste et création de cours
  - Modification / désactivation
  - Suppression unitaire et en lot avec cascade
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
from apps.academics.models import Cours
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.dashboard.forms_admin import CoursForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_courses(request):
    """Liste et création de cours"""

    if request.method == "POST":
        form = CoursForm(request.POST)
        if form.is_valid():
            cours = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création du cours '{cours.code_cours} - {cours.nom_cours}' (Département: {cours.id_departement.nom_departement}, Seuil: {cours.get_seuil_absence()}%) - Gestion structure académique - Secrétaire",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(request, f"Cours '{cours.code_cours}' créé avec succès.")
            return redirect("dashboard:secretary_courses")
    else:
        form = CoursForm()

    courses = (
        Cours.objects.select_related(
            "id_departement", "id_departement__id_faculte", "professeur"
        )
        .all()
        .order_by("code_cours")
    )

    paginator = Paginator(courses, 20)
    courses_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/secretary_courses.html",
        {"courses": courses_page, "form": form},
    )


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_course_edit(request, course_id):
    """Modification ou désactivation d'un cours"""

    cours = get_object_or_404(Cours, id_cours=course_id)

    if request.method == "POST":
        form = CoursForm(request.POST, instance=cours)
        if form.is_valid():
            old_code = cours.code_cours
            cours = form.save()
            action = "modifié" if cours.actif else "désactivé"
            log_action(
                request.user,
                f"CRITIQUE: Cours '{old_code}' {action} (Gestion structure académique - Secrétaire)",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(request, f"Cours '{cours.code_cours}' {action} avec succès.")
            return redirect("dashboard:secretary_courses")
    else:
        form = CoursForm(instance=cours)

    has_prerequisites_options = form.fields["prerequisites"].queryset.exists()

    return render(
        request,
        "dashboard/secretary_course_edit.html",
        {
            "course": cours,
            "form": form,
            "has_prerequisites_options": has_prerequisites_options,
        },
    )


@login_required
@secretary_required
@require_http_methods(["POST"])
def secretary_course_delete(request, course_id):
    """Suppression d'un cours avec suppression en cascade des inscriptions et absences"""

    cours = get_object_or_404(Cours, id_cours=course_id)
    cours_code = cours.code_cours
    cours_nom = cours.nom_cours
    dept_nom = cours.id_departement.nom_departement

    try:
        inscriptions = Inscription.objects.filter(id_cours=cours)
        inscriptions_count = inscriptions.count()
        absences = Absence.objects.filter(id_inscription__in=inscriptions)
        absences_count = absences.count()
        justifications = Justification.objects.filter(id_absence__in=absences)
        justifications_count = justifications.count()
        seances = Seance.objects.filter(id_cours=cours)
        seances_count = seances.count()

        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()

        cascade_info = []
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} séance(s)")
        if absences_count > 0:
            cascade_info.append(f"{absences_count} absence(s)")
        if justifications_count > 0:
            cascade_info.append(f"{justifications_count} justification(s)")

        log_action(
            request.user,
            f"CRITIQUE: Suppression du cours '{cours_code} - {cours_nom}' (Département: {dept_nom}, ID: {course_id}) - Gestion structure académique - Secrétaire",
            request,
            niveau="CRITIQUE",
            objet_type="COURS",
            objet_id=course_id,
        )
        success_msg = f"Cours '{cours_code}' supprimé avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)

    except ProtectedError as e:
        by_type = {}
        for obj in e.protected_objects:
            label = obj._meta.verbose_name
            by_type.setdefault(label, 0)
            by_type[label] += 1
        summary = ", ".join(f"{count} {label}(s)" for label, count in by_type.items())
        logger.error("ProtectedError lors de la suppression du cours %s: %s", cours_code, e)
        messages.error(
            request,
            f"Impossible de supprimer le cours '{cours_code}'. Objets liés bloquants : {summary}.",
        )
    except Exception:
        logger.exception("Erreur lors de la suppression du cours %s", cours_code)
        messages.error(request, f"Erreur lors de la suppression du cours '{cours_code}'.")

    return redirect("dashboard:secretary_courses")


@login_required
@secretary_required
@require_http_methods(["POST"])
def secretary_courses_delete_multiple(request):
    """Suppression multiple de cours avec cascade"""

    raw_ids = request.POST.getlist("course_ids")
    if not raw_ids:
        messages.error(request, "Aucun cours sélectionné.")
        return redirect("dashboard:secretary_courses")

    course_ids = []
    for raw_id in raw_ids:
        try:
            course_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    course_ids = list(dict.fromkeys(course_ids))

    if not course_ids:
        messages.error(request, "Aucun identifiant de cours valide reçu.")
        return redirect("dashboard:secretary_courses")

    deleted_count = 0
    failed_names = []

    try:
        with transaction.atomic():
            courses_qs = Cours.objects.select_for_update().filter(id_cours__in=course_ids)
            for cours in list(courses_qs):
                try:
                    inscriptions = Inscription.objects.filter(id_cours=cours)
                    absences = Absence.objects.filter(id_inscription__in=inscriptions)
                    justifications = Justification.objects.filter(id_absence__in=absences)
                    seances = Seance.objects.filter(id_cours=cours)

                    cascade_parts = []
                    jc = justifications.count()
                    ac = absences.count()
                    ic = inscriptions.count()
                    sc = seances.count()

                    justifications.delete()
                    absences.delete()
                    inscriptions.delete()
                    seances.delete()

                    if sc:
                        cascade_parts.append(f"{sc} séance(s)")
                    if ic:
                        cascade_parts.append(f"{ic} inscription(s)")
                    if ac:
                        cascade_parts.append(f"{ac} absence(s)")
                    if jc:
                        cascade_parts.append(f"{jc} justification(s)")

                    log_action(
                        request.user,
                        f"CRITIQUE: Suppression du cours '{cours.code_cours} - {cours.nom_cours}' "
                        f"(Département: {cours.id_departement.nom_departement}, ID: {cours.id_cours})"
                        f" - Suppression multiple - Secrétaire",
                        request,
                        niveau="CRITIQUE",
                        objet_type="COURS",
                        objet_id=cours.id_cours,
                    )
                    cours.delete()
                    deleted_count += 1

                except Exception:
                    logger.exception("Erreur suppression cours %s", cours.code_cours)
                    failed_names.append(cours.code_cours)

    except Exception:
        logger.exception("Erreur lors de la suppression multiple de cours")
        messages.error(request, "Erreur lors de la suppression multiple. Veuillez réessayer.")
        return redirect("dashboard:secretary_courses")

    if deleted_count:
        messages.success(request, f"{deleted_count} cours supprimé(s) avec succès.")
    if failed_names:
        messages.error(
            request,
            f"Impossible de supprimer : {', '.join(failed_names)}. Vérifiez les dépendances.",
        )

    return redirect("dashboard:secretary_courses")
