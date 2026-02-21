import csv
import logging
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.db.models.deletion import ProtectedError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from django_ratelimit.decorators import ratelimit

logger = logging.getLogger(__name__)

from apps.absences.models import Absence, Justification
from apps.academic_sessions.models import AnneeAcademique
from apps.academics.models import Cours, Departement, Faculte
from apps.accounts.models import User
from apps.audits.ip_utils import ratelimit_client_ip
from apps.audits.models import LogAudit
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
    SystemSettingsForm,
    UserForm,
)
from apps.dashboard.models import SystemSettings
from apps.enrollments.models import Inscription


def is_admin(user):
    """
    VÃ©rifie si l'utilisateur est un administrateur.
    IMPORTANT: SÃ©parÃ© de is_secretary() pour Ã©viter la confusion des rÃ´les.
    """
    return user.is_authenticated and user.role == User.Role.ADMIN


@admin_required
def admin_dashboard_main(request):
    """
    Tableau de bord principal de l'administrateur avec KPIs et vue d'ensemble.
    IMPORTANT: L'administrateur configure et audite, il ne gÃ¨re PAS les opÃ©rations quotidiennes.
    """

    # RÃ©cupÃ©rer l'annÃ©e acadÃ©mique active
    academic_year = AnneeAcademique.objects.filter(active=True).first()

    # KPI 1: Nombre total d'Ã©tudiants
    total_students = User.objects.filter(role=User.Role.ETUDIANT, actif=True).count()

    # KPI 2: Nombre total de professeurs
    total_professors = User.objects.filter(
        role=User.Role.PROFESSEUR, actif=True
    ).count()

    # KPI 3: Nombre de secrÃ©taires
    total_secretaries = User.objects.filter(
        role=User.Role.SECRETAIRE, actif=True
    ).count()

    # KPI 4: Nombre de cours actifs
    # Pour le dashboard admin, on compte tous les cours actifs (configurÃ©s et prÃªts Ã  Ãªtre utilisÃ©s)
    # Un cours est considÃ©rÃ© comme "actif" s'il est marquÃ© comme actif dans le systÃ¨me
    active_courses = Cours.objects.filter(actif=True).count()

    # Optionnel : Compter aussi les cours avec professeur assignÃ© ET utilisÃ©s dans l'annÃ©e active
    # (pour avoir une vue plus dÃ©taillÃ©e)
    if academic_year:
        active_courses_with_activity = (
            Cours.objects.filter(actif=True, professeur__isnull=False)
            .filter(
                Q(
                    id_cours__in=Inscription.objects.filter(
                        id_annee=academic_year
                    ).values_list("id_cours", flat=True)
                )
                | Q(
                    id_cours__in=academic_year.seances.values_list(
                        "id_cours", flat=True
                    )
                )
            )
            .distinct()
            .count()
        )
    else:
        active_courses_with_activity = 0

    # KPI 5: Nombre d'alertes systÃ¨me (Ã©tudiants Ã  risque > 40%)
    at_risk_count = 0
    all_inscriptions = Inscription.objects.select_related(
        "id_cours", "id_etudiant"
    ).all()
    inscription_ids = list(all_inscriptions.values_list("id_inscription", flat=True))
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids, statut="NON_JUSTIFIEE"
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    for ins in all_inscriptions:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = absence_sums.get(ins.id_inscription, 0) or 0
            rate = (total_abs / cours.nombre_total_periodes) * 100
            if rate >= 40 and not ins.exemption_40:
                at_risk_count += 1

    # KPI 6: Nombre d'actions critiques (journaux d'audit des 7 derniers jours)
    seven_days_ago = timezone.now() - timedelta(days=7)
    critical_actions = LogAudit.objects.filter(
        date_action__gte=seven_days_ago, niveau="CRITIQUE"
    ).count()

    # KPI 7: Total d'inscriptions actives
    if academic_year:
        total_inscriptions = Inscription.objects.filter(id_annee=academic_year).count()
    else:
        total_inscriptions = 0

    # KPI 8: Total d'absences enregistrÃ©es (annÃ©e active)
    if academic_year:
        total_absences = Absence.objects.filter(
            id_inscription__id_annee=academic_year
        ).count()
    else:
        total_absences = 0

    # Journaux d'audit rÃ©cents
    recent_audits = LogAudit.objects.select_related("id_utilisateur").order_by(
        "-date_action"
    )[:10]

    # ParamÃ¨tres systÃ¨me
    settings = SystemSettings.get_settings()

    context = {
        "total_students": total_students,
        "total_professors": total_professors,
        "total_secretaries": total_secretaries,
        "active_courses": active_courses,
        "system_alerts": at_risk_count,
        "critical_actions": critical_actions,
        "total_inscriptions": total_inscriptions,
        "total_absences": total_absences,
        "recent_audits": recent_audits,
        "academic_year": academic_year,
        "settings": settings,
    }

    return render(request, "dashboard/admin_dashboard.html", context)


# ========== GESTION DE LA STRUCTURE ACADÃ‰MIQUE ==========


@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculties(request):
    """Liste et crÃ©ation de facultÃ©s"""

    if request.method == "POST":
        form = FaculteForm(request.POST)
        if form.is_valid():
            faculte = form.save()
            log_action(
                request.user,
                f"CRITIQUE: CrÃ©ation de la facultÃ© '{faculte.nom_faculte}' (Configuration systÃ¨me)",
                request,
                niveau="CRITIQUE",
                objet_type="FACULTE",
                objet_id=faculte.id_faculte,
            )
            messages.success(
                request, f"FacultÃ© '{faculte.nom_faculte}' crÃ©Ã©e avec succÃ¨s."
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


@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculty_edit(request, faculte_id):
    """Modification ou dÃ©sactivation d'une facultÃ©"""

    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)

    if request.method == "POST":
        form = FaculteForm(request.POST, instance=faculte)
        if form.is_valid():
            old_name = faculte.nom_faculte
            faculte = form.save()
            action = "modifiÃ©e" if faculte.actif else "dÃ©sactivÃ©e"
            log_action(
                request.user,
                f"CRITIQUE: FacultÃ© '{old_name}' {action} (Configuration systÃ¨me - {'Activation' if faculte.actif else 'DÃ©sactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="FACULTE",
                objet_id=faculte.id_faculte,
            )
            messages.success(
                request, f"FacultÃ© '{faculte.nom_faculte}' {action} avec succÃ¨s."
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


@admin_required
@require_http_methods(["GET", "POST"])
def admin_faculty_delete(request, faculte_id):
    """Suppression d'une facultÃ© avec suppression en cascade des dÃ©partements et cours"""

    faculte = get_object_or_404(Faculte, id_faculte=faculte_id)
    faculte_nom = faculte.nom_faculte

    # FIX VERT #19 — Calcul de l'impact cascade AVANT suppression pour confirmation.
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

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
            item for item in [
                {"count": departements_count, "label": "département(s)"},
                {"count": cours_count, "label": "cours"},
                {"count": seances_count, "label": "séance(s)"},
                {"count": inscriptions_count, "label": "inscription(s)"},
                {"count": absences_count, "label": "absence(s)"},
                {"count": justifications_count, "label": "justification(s)"},
            ] if item["count"] > 0
        ]
        return render(request, "dashboard/admin_confirm_delete.html", {
            "object_label": f"Faculté « {faculte_nom} »",
            "cascade_items": cascade_items,
            "cancel_url": "/dashboard/admin/faculties/",
            "cancel_label": "Facultés",
        })

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
            cascade_info.append(f"{departements_count} dÃ©partement(s)")
        if cours_count > 0:
            cascade_info.append(f"{cours_count} cours")
        if inscriptions_count > 0:
            cascade_info.append(f"{inscriptions_count} inscription(s)")
        if seances_count > 0:
            cascade_info.append(f"{seances_count} sÃ©ance(s)")
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
            f"CRITIQUE: Suppression de la facultÃ© '{faculte_nom}' (ID: {faculte_id}){cascade_msg} - Configuration systÃ¨me",
            request,
            niveau="CRITIQUE",
            objet_type="FACULTE",
            objet_id=faculte_id,
        )

        success_msg = f"FacultÃ© '{faculte_nom}' supprimÃ©e avec succÃ¨s."
        if cascade_info:
            success_msg += (
                f" Suppression en cascade effectuÃ©e : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # GÃ©rer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression de la facultÃ© {faculte_nom}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer la facultÃ© '{faculte_nom}'. "
            f"DÃ©pendances trouvÃ©es : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces Ã©lÃ©ments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression de la facultÃ© {faculte_nom}: {e}",
            exc_info=True,
        )
        messages.error(
            request,
            f"Erreur lors de la suppression de la facultÃ© '{faculte_nom}'. "
            f"Veuillez vÃ©rifier les dÃ©pendances ou contacter l'administrateur systÃ¨me.",
        )

    return redirect("dashboard:admin_faculties")


@admin_required
@require_http_methods(["GET", "POST"])
def admin_departments(request):
    """Liste et crÃ©ation de dÃ©partements"""

    if request.method == "POST":
        form = DepartementForm(request.POST)
        if form.is_valid():
            dept = form.save()
            log_action(
                request.user,
                f"CRITIQUE: CrÃ©ation du dÃ©partement '{dept.nom_departement}' dans la facultÃ© '{dept.id_faculte.nom_faculte}' (Configuration systÃ¨me)",
                request,
                niveau="CRITIQUE",
                objet_type="DEPARTEMENT",
                objet_id=dept.id_departement,
            )
            messages.success(
                request, f"DÃ©partement '{dept.nom_departement}' crÃ©Ã© avec succÃ¨s."
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


@admin_required
@require_http_methods(["GET", "POST"])
def admin_department_edit(request, dept_id):
    """Modification ou dÃ©sactivation d'un dÃ©partement"""

    dept = get_object_or_404(Departement, id_departement=dept_id)

    if request.method == "POST":
        form = DepartementForm(request.POST, instance=dept)
        if form.is_valid():
            old_name = dept.nom_departement
            dept = form.save()
            action = "modifiÃ©" if dept.actif else "dÃ©sactivÃ©"
            log_action(
                request.user,
                f"CRITIQUE: DÃ©partement '{old_name}' {action} (Configuration systÃ¨me - {'Activation' if dept.actif else 'DÃ©sactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="DEPARTEMENT",
                objet_id=dept.id_departement,
            )
            messages.success(
                request, f"DÃ©partement '{dept.nom_departement}' {action} avec succÃ¨s."
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


@admin_required
@require_http_methods(["GET", "POST"])
def admin_department_delete(request, dept_id):
    """Suppression d'un dÃ©partement avec suppression en cascade des cours"""

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
            item for item in [
                {"count": cours_count, "label": "cours"},
                {"count": seances_count, "label": "séance(s)"},
                {"count": inscriptions_count, "label": "inscription(s)"},
                {"count": absences_count, "label": "absence(s)"},
                {"count": justifications_count, "label": "justification(s)"},
            ] if item["count"] > 0
        ]
        return render(request, "dashboard/admin_confirm_delete.html", {
            "object_label": f"Département « {dept_nom} » (Faculté : {faculte_nom})",
            "cascade_items": cascade_items,
            "cancel_url": "/dashboard/admin/departments/",
            "cancel_label": "Départements",
        })

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
            cascade_info.append(f"{seances_count} sÃ©ance(s)")
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
            f"CRITIQUE: Suppression du dÃ©partement '{dept_nom}' (FacultÃ©: {faculte_nom}, ID: {dept_id}){cascade_msg} - Configuration systÃ¨me",
            request,
            niveau="CRITIQUE",
            objet_type="DEPARTEMENT",
            objet_id=dept_id,
        )

        success_msg = f"DÃ©partement '{dept_nom}' supprimÃ© avec succÃ¨s."
        if cascade_info:
            success_msg += (
                f" Suppression en cascade effectuÃ©e : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # GÃ©rer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression du dÃ©partement {dept_nom}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer le dÃ©partement '{dept_nom}'. "
            f"DÃ©pendances trouvÃ©es : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces Ã©lÃ©ments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression du dÃ©partement {dept_nom}: {e}",
            exc_info=True,
        )
        messages.error(
            request,
            f"Erreur lors de la suppression du dÃ©partement '{dept_nom}'. "
            f"Veuillez vÃ©rifier les dÃ©pendances ou contacter l'administrateur systÃ¨me.",
        )

    return redirect("dashboard:admin_departments")


@admin_required
@require_http_methods(["GET", "POST"])
def admin_courses(request):
    """Liste et crÃ©ation de cours"""

    if request.method == "POST":
        form = CoursForm(request.POST)
        if form.is_valid():
            cours = form.save()
            log_action(
                request.user,
                f"CRITIQUE: CrÃ©ation du cours '{cours.code_cours} - {cours.nom_cours}' (DÃ©partement: {cours.id_departement.nom_departement}, Seuil: {cours.get_seuil_absence()}%)",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(
                request, f"Cours '{cours.code_cours}' crÃ©Ã© avec succÃ¨s."
            )
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


@admin_required
@require_http_methods(["GET", "POST"])
def admin_course_edit(request, course_id):
    """Modification ou dÃ©sactivation d'un cours"""

    cours = get_object_or_404(Cours, id_cours=course_id)

    if request.method == "POST":
        form = CoursForm(request.POST, instance=cours)
        if form.is_valid():
            old_code = cours.code_cours
            cours = form.save()
            action = "modifiÃ©" if cours.actif else "dÃ©sactivÃ©"
            log_action(
                request.user,
                f"CRITIQUE: Cours '{old_code}' {action} (Configuration systÃ¨me - {'Activation' if cours.actif else 'DÃ©sactivation'})",
                request,
                niveau="CRITIQUE",
                objet_type="COURS",
                objet_id=cours.id_cours,
            )
            messages.success(
                request, f"Cours '{cours.code_cours}' {action} avec succÃ¨s."
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
            item for item in [
                {"count": seances_count, "label": "séance(s)"},
                {"count": inscriptions_count, "label": "inscription(s)"},
                {"count": absences_count, "label": "absence(s)"},
                {"count": justifications_count, "label": "justification(s)"},
            ] if item["count"] > 0
        ]
        return render(request, "dashboard/admin_confirm_delete.html", {
            "object_label": f"Cours « {cours_code} — {cours_nom} » (Département : {dept_nom})",
            "cascade_items": cascade_items,
            "cancel_url": "/dashboard/admin/courses/",
            "cancel_label": "Cours",
        })

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
            cascade_info.append(f"{seances_count} sÃ©ance(s)")
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
            f"CRITIQUE: Suppression du cours '{cours_code} - {cours_nom}' (DÃ©partement: {dept_nom}, ID: {course_id}){cascade_msg} - Configuration systÃ¨me",
            request,
            niveau="CRITIQUE",
            objet_type="COURS",
            objet_id=course_id,
        )

        success_msg = f"Cours '{cours_code}' supprimÃ© avec succÃ¨s."
        if cascade_info:
            success_msg += (
                f" Suppression en cascade effectuÃ©e : {', '.join(cascade_info)}."
            )
        messages.success(request, success_msg)

    except ProtectedError as e:
        # GÃ©rer les erreurs PROTECT
        protected_objects = []
        for obj in e.protected_objects:
            protected_objects.append(str(obj))

        logger.error(
            f"ProtectedError lors de la suppression du cours {cours_code}: {e}"
        )
        messages.error(
            request,
            f"Impossible de supprimer le cours '{cours_code}'. "
            f"DÃ©pendances trouvÃ©es : {', '.join(protected_objects)}. "
            f"Veuillez d'abord supprimer ou modifier ces Ã©lÃ©ments.",
        )
    except Exception as e:
        logger.error(
            f"Erreur lors de la suppression du cours {cours_code}: {e}", exc_info=True
        )
        messages.error(
            request,
            f"Erreur lors de la suppression du cours '{cours_code}'. "
            f"Veuillez vÃ©rifier les dÃ©pendances ou contacter l'administrateur systÃ¨me.",
        )

    return redirect("dashboard:admin_courses")


# ========== GESTION DES UTILISATEURS ==========


@admin_required
def admin_users(request):
    """Liste et gestion des utilisateurs"""

    # Filtres
    role_filter = request.GET.get("role", "")
    search_query = request.GET.get("q", "")
    active_filter = request.GET.get("active", "")

    users = User.objects.all()

    if role_filter:
        users = users.filter(role=role_filter)
    if search_query:
        users = users.filter(
            Q(nom__icontains=search_query)
            | Q(prenom__icontains=search_query)
            | Q(email__icontains=search_query)
        )
    if active_filter == "true":
        users = users.filter(actif=True)
    elif active_filter == "false":
        users = users.filter(actif=False)

    users = users.order_by("nom", "prenom")

    # Pagination
    paginator = Paginator(users, 25)
    page = request.GET.get("page")
    users_page = paginator.get_page(page)

    return render(
        request,
        "dashboard/admin_users.html",
        {
            "users": users_page,
            "role_filter": role_filter,
            "search_query": search_query,
            "active_filter": active_filter,
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_create(request):
    """CrÃ©ation d'un nouvel utilisateur"""

    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(
                request.user,
                f"CRITIQUE: CrÃ©ation de l'utilisateur '{user.email}' (RÃ´le: {user.get_role_display()}, Nom: {user.get_full_name()}) - Gestion des utilisateurs",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.id_utilisateur,
            )
            messages.success(
                request, f"Utilisateur '{user.email}' crÃ©Ã© avec succÃ¨s."
            )
            return redirect("dashboard:admin_users")
    else:
        form = UserForm()

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "title": "CrÃ©er un utilisateur",
            "editing_user": None,  # Pas d'utilisateur en cours d'Ã©dition lors de la crÃ©ation
        },
    )


@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_edit(request, user_id):
    """Modification d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    if request.method == "POST":
        old_role = user.role
        old_active = user.actif
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()

            # Journaliser les changements de rÃ´le
            if old_role != user.role:
                old_role_display = dict(User.Role.choices).get(old_role, old_role)
                log_action(
                    request.user,
                    f"CRITIQUE: Modification du rÃ´le de '{user.email}' de {old_role_display} Ã  {user.get_role_display()} - Gestion des utilisateurs",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )
            if old_active != user.actif:
                action = "activÃ©" if user.actif else "dÃ©sactivÃ©"
                log_action(
                    request.user,
                    f"CRITIQUE: Compte '{user.email}' {action} (Gestion des utilisateurs - {'RÃ©activation' if user.actif else 'DÃ©sactivation'})",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )

            messages.success(
                request, f"Utilisateur '{user.email}' modifiÃ© avec succÃ¨s."
            )
            return redirect("dashboard:admin_users")
    else:
        form = UserForm(instance=user)

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "editing_user": user,  # Utilisateur en cours d'Ã©dition
            "title": f"Modifier l'utilisateur {user.get_full_name()}",
        },
    )


@admin_required
@require_http_methods(["POST"])
def admin_user_reset_password(request, user_id):
    """RÃ©initialisation du mot de passe d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    new_password = (request.POST.get("new_password") or "").strip()
    if not new_password:
        messages.error(request, "Le mot de passe ne peut pas Ãªtre vide.")
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    user.set_password(new_password)
    # Forcer l'utilisateur Ã  changer son mot de passe Ã  la prochaine connexion
    user.must_change_password = True
    user.save()
    log_action(
        request.user,
        f"CRITIQUE: RÃ©initialisation du mot de passe pour '{user.email}' (Gestion des utilisateurs - Action de sÃ©curitÃ©)",
        request,
        niveau="CRITIQUE",
        objet_type="USER",
        objet_id=user.id_utilisateur,
    )
    messages.success(
        request,
        f"Mot de passe rÃ©initialisÃ© pour '{user.email}'. L'utilisateur devra le changer lors de sa prochaine connexion.",
    )

    return redirect("dashboard:admin_user_edit", user_id=user_id)


@admin_required
def admin_user_audit(request, user_id):
    """Consultation des journaux d'audit pour un utilisateur spÃ©cifique"""

    user = get_object_or_404(User, id_utilisateur=user_id)
    logs = LogAudit.objects.filter(id_utilisateur=user).order_by("-date_action")

    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get("page")
    logs_page = paginator.get_page(page)

    return render(
        request,
        "dashboard/admin_user_audit.html",
        {
            "user": user,
            "logs": logs_page,
        },
    )


@admin_required
@require_http_methods(["POST"])
def admin_users_delete_multiple(request):
    """Suppression multiple d'utilisateurs avec verifications de securite"""

    try:
        raw_user_ids = request.POST.getlist("user_ids")

        if not raw_user_ids:
            messages.error(request, "Aucun utilisateur selectionne.")
            return redirect("dashboard:admin_users")

        user_ids = []
        for raw_user_id in raw_user_ids:
            try:
                user_ids.append(int(raw_user_id))
            except (TypeError, ValueError):
                continue
        # Deduplicate while preserving input order.
        user_ids = list(dict.fromkeys(user_ids))

        if not user_ids:
            messages.error(request, "Aucun identifiant utilisateur valide recu.")
            return redirect("dashboard:admin_users")

        deleted_count = 0
        deactivated_count = 0
        failed_count = 0
        errors = []

        with transaction.atomic():
            # Lock targeted users to prevent concurrent create/delete races on FK references.
            locked_users = list(
                User.objects.select_for_update().filter(id_utilisateur__in=user_ids)
            )
            users_by_id = {user.id_utilisateur: user for user in locked_users}

            selected_user_ids = [
                uid for uid in users_by_id.keys() if uid != request.user.id_utilisateur
            ]

            inscriptions_count_map = {}
            absences_encoded_count_map = {}
            audit_logs_count_map = {}
            cours_count_map = {}

            if selected_user_ids:
                inscriptions_count_map = dict(
                    Inscription.objects.filter(id_etudiant_id__in=selected_user_ids)
                    .values("id_etudiant_id")
                    .annotate(total=Count("id_inscription"))
                    .values_list("id_etudiant_id", "total")
                )
                absences_encoded_count_map = dict(
                    Absence.objects.filter(encodee_par_id__in=selected_user_ids)
                    .values("encodee_par_id")
                    .annotate(total=Count("id_absence"))
                    .values_list("encodee_par_id", "total")
                )
                audit_logs_count_map = dict(
                    LogAudit.objects.filter(id_utilisateur_id__in=selected_user_ids)
                    .values("id_utilisateur_id")
                    .annotate(total=Count("id_log"))
                    .values_list("id_utilisateur_id", "total")
                )
                cours_count_map = dict(
                    Cours.objects.filter(professeur_id__in=selected_user_ids)
                    .values("professeur_id")
                    .annotate(total=Count("id_cours"))
                    .values_list("professeur_id", "total")
                )

            to_deactivate_ids = {
                uid
                for uid in selected_user_ids
                if (
                    inscriptions_count_map.get(uid, 0) > 0
                    or absences_encoded_count_map.get(uid, 0) > 0
                    or audit_logs_count_map.get(uid, 0) > 0
                )
            }
            if to_deactivate_ids:
                User.objects.filter(id_utilisateur__in=to_deactivate_ids).update(
                    actif=False
                )

            for user_id in user_ids:
                try:
                    user = users_by_id.get(user_id)
                    if not user:
                        errors.append(f"Utilisateur avec ID {user_id} introuvable")
                        failed_count += 1
                        continue

                    if user == request.user:
                        errors.append(
                            f"Vous ne pouvez pas supprimer votre propre compte ({user.email})"
                        )
                        failed_count += 1
                        continue

                    if user.id_utilisateur in to_deactivate_ids:
                        log_action(
                            request.user,
                            f"CRITIQUE: Desactivation de l'utilisateur '{user.email}' (ID: {user.id_utilisateur}) - Dependances detectees (suppression multiple)",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user.id_utilisateur,
                        )
                        deactivated_count += 1
                        continue

                    cours_count = cours_count_map.get(user.id_utilisateur, 0)
                    if cours_count > 0:
                        Cours.objects.filter(professeur=user).update(professeur=None)

                    user_email = user.email
                    user_name = user.get_full_name()
                    user_role = user.get_role_display()
                    user_id_for_log = user.id_utilisateur

                    try:
                        user.delete()
                        log_action(
                            request.user,
                            f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Role: {user_role}, Nom: {user_name}) - Suppression multiple",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user_id_for_log,
                        )
                        deleted_count += 1
                    except ProtectedError:
                        # Safety net against edge cases during concurrent write loads.
                        User.objects.filter(id_utilisateur=user_id_for_log).update(
                            actif=False
                        )
                        log_action(
                            request.user,
                            f"CRITIQUE: Desactivation de l'utilisateur '{user_email}' (ID: {user_id_for_log}) - Dependances detectees pendant suppression",
                            request,
                            niveau="CRITIQUE",
                            objet_type="USER",
                            objet_id=user_id_for_log,
                        )
                        deactivated_count += 1
                except Exception:
                    logger.exception(
                        "Erreur lors de la suppression de l'utilisateur %s", user_id
                    )
                    errors.append(
                        "Erreur interne lors de la suppression de cet utilisateur."
                    )
                    failed_count += 1

        if deleted_count > 0:
            messages.success(
                request, f"{deleted_count} utilisateur(s) supprime(s) avec succes."
            )
        if deactivated_count > 0:
            messages.warning(
                request,
                f"{deactivated_count} utilisateur(s) desactive(s) (dependances detectees).",
            )
        if failed_count > 0:
            error_msg = f"{failed_count} utilisateur(s) n'ont pas pu etre supprime(s)."
            if errors:
                error_msg += " Details : " + " ; ".join(errors[:5])
            messages.error(request, error_msg)

        return redirect("dashboard:admin_users")

    except Exception:
        logger.exception("Erreur lors de la suppression multiple")
        messages.error(
            request,
            "Erreur interne lors de la suppression multiple. "
            "Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )
        return redirect("dashboard:admin_users")


@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_delete(request, user_id):
    """Suppression d'un utilisateur avec verifications de securite"""

    try:
        user = get_object_or_404(User, id_utilisateur=user_id)

        # Verification 1: Ne pas supprimer soi-meme
        if user == request.user:
            messages.error(request, "Vous ne pouvez pas supprimer votre propre compte.")
            return redirect("dashboard:admin_users")

        inscriptions_count = Inscription.objects.filter(id_etudiant=user).count()
        absences_encoded_count = Absence.objects.filter(encodee_par=user).count()
        audit_logs_count = LogAudit.objects.filter(id_utilisateur=user).count()
        cours_count = Cours.objects.filter(professeur=user).count()

        # FIX VERT #19 — Page de confirmation avant suppression définitive
        if request.method == "GET":
            if inscriptions_count > 0 or absences_encoded_count > 0 or audit_logs_count > 0:
                # Pas de page de confirmation : on sait déjà que ce sera une désactivation
                cascade_items = [
                    item for item in [
                        {"count": inscriptions_count, "label": "inscription(s)"},
                        {"count": absences_encoded_count, "label": "absence(s) encodée(s)"},
                        {"count": audit_logs_count, "label": "entrée(s) d'audit"},
                    ] if item["count"] > 0
                ]
                return render(request, "dashboard/admin_confirm_delete.html", {
                    "object_label": f"Utilisateur « {user.get_full_name()} » ({user.email})",
                    "cascade_items": cascade_items,
                    "extra_warning": "Des dépendances ont été détectées. Le compte sera DÉSACTIVÉ (pas supprimé).",
                    "cancel_url": "/dashboard/admin/users/",
                    "cancel_label": "Utilisateurs",
                })
            else:
                cascade_items = [
                    item for item in [
                        {"count": cours_count, "label": "cours (sera détaché du professeur)"},
                    ] if item["count"] > 0
                ]
                return render(request, "dashboard/admin_confirm_delete.html", {
                    "object_label": f"Utilisateur « {user.get_full_name()} » ({user.email})",
                    "cascade_items": cascade_items,
                    "cancel_url": "/dashboard/admin/users/",
                    "cancel_label": "Utilisateurs",
                })

        if inscriptions_count > 0 or absences_encoded_count > 0 or audit_logs_count > 0:
            user.actif = False
            user.save(update_fields=["actif"])
            log_action(
                request.user,
                f"CRITIQUE: Desactivation de l'utilisateur '{user.email}' (ID: {user.id_utilisateur}) - Dependances detectees",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.id_utilisateur,
            )
            messages.warning(
                request,
                "Suppression bloquee: l'utilisateur a des dependances. Le compte a ete desactive.",
            )
            return redirect("dashboard:admin_users")

        user_email = user.email
        user_name = user.get_full_name()
        user_role = user.get_role_display()
        user_id_for_log = user.id_utilisateur

        with transaction.atomic():
            if cours_count > 0:
                Cours.objects.filter(professeur=user).update(professeur=None)

            try:
                user.groups.clear()
                user.user_permissions.clear()
            except Exception:
                pass

            user.delete()

            # CORRECTION BUG CRITIQUE #6 — log_action déplacé dans la transaction atomique
            # Avant : si log_action échouait après user.delete(), l'audit était perdu
            # mais la suppression était commitée. Désormais : atomicité ACID garantie
            # (si le log échoue, toute la transaction rollback, utilisateur non supprimé).
            log_action(
                request.user,
                f"CRITIQUE: Suppression de l'utilisateur '{user_email}' (ID: {user_id_for_log}, Role: {user_role}, Nom: {user_name}) - Gestion des utilisateurs",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user_id_for_log,
            )

        messages.success(request, f"Utilisateur '{user_email}' supprime avec succes.")
        return redirect("dashboard:admin_users")

    except Exception:
        logger.exception(
            "Exception lors de la recuperation de l'utilisateur %s", user_id
        )
        messages.error(
            request,
            "Erreur interne lors de la suppression de l'utilisateur. "
            "Veuillez verifier les dependances ou contacter l'administrateur systeme.",
        )
        return redirect("dashboard:admin_users")


# ========== PARAMÃˆTRES SYSTÃˆME ==========


@admin_required
@require_http_methods(["GET", "POST"])
def admin_settings(request):
    """Gestion des paramÃ¨tres systÃ¨me globaux"""

    settings = SystemSettings.get_settings()

    if request.method == "POST":
        old_threshold = settings.default_absence_threshold
        form = SystemSettingsForm(request.POST, instance=settings)
        if form.is_valid():
            settings = form.save(commit=False)
            settings.modified_by = request.user
            settings.save()

            # Journaliser les changements de seuil
            if old_threshold != settings.default_absence_threshold:
                log_action(
                    request.user,
                    f"CRITIQUE: Modification du seuil d'absence par dÃ©faut de {old_threshold}% Ã  {settings.default_absence_threshold}% (ParamÃ¨tres systÃ¨me - Impact global)",
                    request,
                    niveau="CRITIQUE",
                    objet_type="SYSTEM",
                    objet_id=1,
                )

            log_action(
                request.user,
                f"CRITIQUE: Modification des paramÃ¨tres systÃ¨me (Seuil: {settings.default_absence_threshold}%, Blocage: {settings.get_block_type_display()})",
                request,
                niveau="CRITIQUE",
                objet_type="SYSTEM",
                objet_id=1,
            )
            messages.success(request, "ParamÃ¨tres systÃ¨me mis Ã  jour avec succÃ¨s.")
            return redirect("dashboard:admin_settings")
    else:
        form = SystemSettingsForm(instance=settings)

    return render(
        request,
        "dashboard/admin_settings.html",
        {
            "form": form,
            "settings": settings,
        },
    )


# ========== GESTION DES ANNÃ‰ES ACADÃ‰MIQUES ==========


@admin_required
def admin_academic_years(request):
    """Liste et gestion des annÃ©es acadÃ©miques"""

    if request.method == "POST":
        form = AnneeAcademiqueForm(request.POST)
        if form.is_valid():
            year = form.save()
            log_action(
                request.user,
                f"CRITIQUE: CrÃ©ation de l'annÃ©e acadÃ©mique '{year.libelle}' (Configuration systÃ¨me - {'AnnÃ©e active' if year.active else 'AnnÃ©e inactive'})",
                request,
                niveau="CRITIQUE",
                objet_type="AUTRE",
                objet_id=year.id_annee,
            )
            messages.success(
                request, f"AnnÃ©e acadÃ©mique '{year.libelle}' crÃ©Ã©e avec succÃ¨s."
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


@admin_required
@require_http_methods(["POST"])
def admin_academic_year_set_active(request, year_id):
    """DÃ©finir une annÃ©e acadÃ©mique comme active"""

    year = get_object_or_404(AnneeAcademique, id_annee=year_id)

    # DÃ©sactiver toutes les annÃ©es
    AnneeAcademique.objects.update(active=False)

    # Activer l'annÃ©e sÃ©lectionnÃ©e
    year.active = True
    year.save()

    log_action(
        request.user,
        f"CRITIQUE: AnnÃ©e acadÃ©mique '{year.libelle}' dÃ©finie comme active (Configuration systÃ¨me - Changement d'annÃ©e acadÃ©mique)",
        request,
        niveau="CRITIQUE",
        objet_type="AUTRE",
        objet_id=year.id_annee,
    )
    messages.success(
        request, f"AnnÃ©e acadÃ©mique '{year.libelle}' dÃ©finie comme active."
    )

    return redirect("dashboard:admin_academic_years")


@admin_required
@require_http_methods(["POST"])
def admin_academic_year_delete(request, year_id):
    """Suppression d'une annee academique avec suppression en cascade des inscriptions et seances"""

    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    year_libelle = year.libelle
    is_active = year.active

    try:
        # Compteurs pour les elements supprimes en cascade
        inscriptions_count = 0
        seances_count = 0
        absences_count = 0
        justifications_count = 0

        if is_active:
            messages.error(
                request,
                f"Impossible de supprimer l'annee academique '{year_libelle}' car elle est actuellement active. "
                f"Veuillez d'abord definir une autre annee comme active.",
            )
            return redirect("dashboard:admin_academic_years")

        from apps.academic_sessions.models import Seance

        inscriptions = Inscription.objects.filter(id_annee=year)
        inscriptions_count = inscriptions.count()

        absences = Absence.objects.filter(id_inscription__in=inscriptions)
        absences_count = absences.count()

        justifications = Justification.objects.filter(id_absence__in=absences)
        justifications_count = justifications.count()

        seances = Seance.objects.filter(id_annee=year)
        seances_count = seances.count()

        with transaction.atomic():
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


# ========== JOURNAUX D'AUDIT ==========


@admin_required
def admin_audit_logs(request):
    """Consultation de tous les journaux d'audit avec filtres"""

    # Filtres
    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    user_filter = request.GET.get("user", "")
    search_query = request.GET.get("q", "")

    logs = LogAudit.objects.select_related("id_utilisateur").all()

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        logs = logs.filter(date_action__gte=date_from)
    if date_to:
        logs = logs.filter(date_action__lte=date_to)
    if user_filter:
        logs = logs.filter(
            Q(id_utilisateur__nom__icontains=user_filter)
            | Q(id_utilisateur__prenom__icontains=user_filter)
            | Q(id_utilisateur__email__icontains=user_filter)
        )
    if search_query:
        logs = logs.filter(action__icontains=search_query)

    logs = logs.order_by("-date_action")

    # Pagination
    paginator = Paginator(logs, 50)
    page = request.GET.get("page")
    logs_page = paginator.get_page(page)

    return render(
        request,
        "dashboard/admin_audit_logs.html",
        {
            "logs": logs_page,
            "role_filter": role_filter,
            "action_filter": action_filter,
            "date_from": date_from,
            "date_to": date_to,
            "user_filter": user_filter,
            "search_query": search_query,
        },
    )


# ========== EXPORTS ==========


@admin_required
def admin_export_audit_csv(request):
    """Export des journaux d'audit en CSV"""

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="audit_logs_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv"'
    )

    writer = csv.writer(response)
    writer.writerow(
        ["Date/Heure", "Utilisateur", "Email", "RÃ´le", "Action", "Adresse IP"]
    )

    logs = (
        LogAudit.objects.select_related("id_utilisateur").all().order_by("-date_action")
    )

    # Appliquer les mÃªmes filtres que dans la vue
    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        logs = logs.filter(date_action__gte=date_from)
    if date_to:
        logs = logs.filter(date_action__lte=date_to)

    for log in logs:
        writer.writerow(
            [
                log.date_action.strftime("%Y-%m-%d %H:%M:%S"),
                f"{log.id_utilisateur.prenom} {log.id_utilisateur.nom}",
                log.id_utilisateur.email,
                log.id_utilisateur.get_role_display(),
                log.action,
                log.adresse_ip,
            ]
        )

    log_action(
        request.user,
        "Export des journaux d'audit (CSV)",
        request,
        niveau="INFO",
        objet_type="SYSTEM",
    )
    return response


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
            # AnnÃ©e 2 : prÃ©requis uniquement d'AnnÃ©e 1
            prerequisites = Cours.objects.filter(actif=True, niveau=1)
        elif niveau == 3:
            # AnnÃ©e 3 : prÃ©requis uniquement d'AnnÃ©e 1 ou 2
            prerequisites = Cours.objects.filter(actif=True, niveau__in=[1, 2])
        else:
            return api_error(
                "niveau invalide (doit Ãªtre 1, 2 ou 3)", status=400, code="bad_request"
            )

        # Exclure le cours actuel si on est en mode Ã©dition
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
                    "display": f"[{course.code_cours}] {course.nom_cours} (AnnÃ©e {course.niveau})",
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
