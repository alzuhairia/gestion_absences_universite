import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.audits.ip_utils import ratelimit_client_ip
from apps.audits.utils import log_action
from apps.dashboard.decorators import (
    admin_required,
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
)
from apps.dashboard.forms_admin import (
    AnneeAcademiqueForm,
    CoursForm,
    DepartementForm,
    FaculteForm,
)
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


# ========== GESTION DE LA STRUCTURE ACADÉMIQUE ==========


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
    faculties_page = paginator.get_page(request.GET.get("page"))

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

    # FIX VERT #19 — Calcul de l'impact cascade AVANT suppression pour confirmation.
    from apps.academic_sessions.models import Seance

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

    # GET — page de confirmation avec impact cascade
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

    # POST — exécution de la suppression
    try:
        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()
            departements.delete()
            faculte.delete()

        # Construire le message de cascade
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

        # Journaliser la suppression
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
            success_msg += (
                f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression de la faculté {faculte_nom}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer la faculté '{faculte_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression de la faculté {faculte_nom}: {e}",
            exc_info=True,
        )
        messages.error(
            request,
            f"Erreur lors de la suppression de la faculté '{faculte_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_faculties")


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
    departments_page = paginator.get_page(request.GET.get("page"))

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

    # FIX VERT #19 — Calcul de l'impact cascade AVANT suppression pour confirmation.
    from apps.academic_sessions.models import Seance

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

    # GET — page de confirmation avec impact cascade
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

    # POST — exécution de la suppression
    try:
        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()
            dept.delete()

        # Construire le message de cascade
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

        # Journaliser la suppression
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
            success_msg += (
                f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression du département {dept_nom}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer le département '{dept_nom}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression du département {dept_nom}: {e}",
            exc_info=True,
        )
        messages.error(
            request,
            f"Erreur lors de la suppression du département '{dept_nom}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_departments")


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_courses(request):
    """Liste et création de cours"""

    if request.method == "POST":
        form = CoursForm(request.POST)
        if form.is_valid():
            cours = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création du cours '{cours.code_cours} - {cours.nom_cours}' (Département: {cours.id_departement.nom_departement}, Seuil: {cours.get_seuil_absence()}%)",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(request, f"Cours '{cours.code_cours}' créé avec succès.")
            return redirect("dashboard:admin_courses")
    else:
        form = CoursForm()

    courses = (
        Cours.objects.select_related(
            "id_departement", "id_departement__id_faculte", "professeur"
        )
        .all()
        .order_by("code_cours")
    )

    # Pagination
    paginator = Paginator(courses, 20)
    page = request.GET.get("page")
    courses_page = paginator.get_page(page)

    return render(
        request,
        "dashboard/admin_courses.html",
        {
            "courses": courses_page,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_course_edit(request, course_id):
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
                f"CRITIQUE: Cours '{old_code}' {action} (Configuration système - {'Activation' if cours.actif else 'Désactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(
                request, f"Cours '{cours.code_cours}' {action} avec succès."
            )
            return redirect("dashboard:admin_courses")
    else:
        form = CoursForm(instance=cours)

    return render(
        request,
        "dashboard/admin_course_edit.html",
        {
            "course": cours,
            "form": form,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_course_delete(request, course_id):
    """Suppression d'un cours avec suppression en cascade des inscriptions et absences"""

    cours = get_object_or_404(Cours, id_cours=course_id)
    cours_code = cours.code_cours
    cours_nom = cours.nom_cours
    dept_nom = cours.id_departement.nom_departement

    # FIX VERT #19 — Calcul de l'impact cascade AVANT suppression pour confirmation.
    from apps.academic_sessions.models import Seance

    inscriptions = Inscription.objects.filter(id_cours=cours)
    inscriptions_count = inscriptions.count()
    absences = Absence.objects.filter(id_inscription__in=inscriptions)
    absences_count = absences.count()
    justifications = Justification.objects.filter(id_absence__in=absences)
    justifications_count = justifications.count()
    seances = Seance.objects.filter(id_cours=cours)
    seances_count = seances.count()

    # GET — page de confirmation avec impact cascade
    if request.method == "GET":
        cascade_items = [
            item
            for item in [
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
                "object_label": f"Cours « {cours_code} — {cours_nom} » (Département : {dept_nom})",
                "cascade_items": cascade_items,
                "cancel_url": "/dashboard/admin/courses/",
                "cancel_label": "Cours",
            },
        )

    # POST — exécution de la suppression
    try:
        with transaction.atomic():
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            cours.delete()

        # Construire le message de cascade
        cascade_info = []
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

        # Journaliser la suppression
        log_action(
            request.user,
            f"CRITIQUE: Suppression du cours '{cours_code} - {cours_nom}' (Département: {dept_nom}, ID: {course_id}){cascade_msg} - Configuration système",
            request,
            niveau="CRITIQUE",
            objet_type="COURS",
            objet_id=course_id,
        )

        success_msg = f"Cours '{cours_code}' supprimé avec succès."
        if cascade_info:
            success_msg += (
                f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # Gérer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression du cours {cours_code}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer le cours '{cours_code}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression du cours {cours_code}: {e}", exc_info=True
        )
        messages.error(
            request,
            f"Erreur lors de la suppression du cours '{cours_code}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_courses")


# ========== GESTION DES ANNÉES ACADÉMIQUES ==========


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

    year = get_object_or_404(AnneeAcademique, id_annee=year_id)

    with transaction.atomic():
        AnneeAcademique.objects.update(active=False)
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
    """Suppression d'une annee academique avec suppression en cascade des inscriptions et seances"""

    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    year_libelle = year.libelle

    try:
        from apps.academic_sessions.models import Seance

        with transaction.atomic():
            # Lock the row to prevent TOCTOU race condition
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
            success_msg += (
                f" Suppression en cascade effectuee : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression de l'annee academique {year_libelle}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer l'annee academique '{year_libelle}'. "
            f"Dependances trouvees : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces elements.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression de l'annee academique {year_libelle}: {e}",
            exc_info=True,
        )
        messages.error(
            request,
            f"Erreur lors de la suppression de l'annee academique '{year_libelle}'. "
            f"Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )

    return redirect("dashboard:admin_academic_years")


# ========== API ==========


@ratelimit(key=ratelimit_client_ip, rate="30/5m", method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_prerequisites_by_level(request):
    """
    API — Liste les cours disponibles comme prérequis selon le niveau cible.

    Règle métier : un cours de niveau N ne peut avoir que des prérequis de niveau < N.

    Query params:
        niveau    (int, requis)    : niveau cible (1, 2 ou 3)
        course_id (int, optionnel) : exclut ce cours des résultats (mode édition)

    Réponses:
        200 [{"id": int, "code": str, "name": str, "niveau": int, "display": str}, ...]
        400 {"error": {"code": "bad_request", "message": "..."}}
        401 {"error": {"code": "auth_required", ...}}
        403 {"error": {"code": "forbidden", ...}}
        429 Rate limit dépassé (30/5m par IP)
        500 {"error": {"code": "server_error", ...}}
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )

    niveau = request.GET.get("niveau")
    course_id = request.GET.get(
        "course_id", None
    )  # Pour exclure le cours actuel lors de l'edition

    if not niveau:
        return api_error("niveau requis", status=400, code="bad_request")

    try:
        niveau = int(niveau)
    except ValueError:
        return api_error("niveau invalide", status=400, code="bad_request")

    try:
        # Filtrer selon le niveau
        if niveau == 1:
            # Annee 1 : pas de prerequis
            prerequisites = Cours.objects.none()
        elif niveau == 2:
            # Année 2 : prérequis uniquement d'Année 1
            prerequisites = Cours.objects.filter(actif=True, niveau=1)
        elif niveau == 3:
            # Année 3 : prérequis uniquement d'Année 1 ou 2
            prerequisites = Cours.objects.filter(actif=True, niveau__in=[1, 2])
        else:
            return api_error(
                "niveau invalide (doit être 1, 2 ou 3)", status=400, code="bad_request"
            )

        # Exclure le cours actuel si on est en mode édition
        if course_id:
            try:
                prerequisites = prerequisites.exclude(id_cours=int(course_id))
            except ValueError:
                pass

        data = []
        for course in prerequisites.order_by("niveau", "code_cours"):
            data.append(
                {
                    "id": course.id_cours,
                    "code": course.code_cours,
                    "name": course.nom_cours,
                    "niveau": course.niveau,
                    "display": f"[{course.code_cours}] {course.nom_cours} (Année {course.niveau})",
                }
            )

        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception(
            "Erreur API get_prerequisites_by_level [request_id=%s]", request_id
        )
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )
