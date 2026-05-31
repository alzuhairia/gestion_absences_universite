"""
Vues CRUD des cours pour le tableau de bord administrateur UniAbsences.

Fournit des vues réservées aux administrateurs pour gérer les enregistrements ``Cours`` :

- Lister tous les cours (paginés) et en créer de nouveaux via ``CoursForm``.
- Modifier ou désactiver (soft-deactivate) un cours existant.
- Supprimer un cours unique avec cascade manuel :
  ``Justification → Absence → Inscription / Seance → Cours``.
- Supprimer en masse plusieurs cours sélectionnés depuis la page de liste ; chaque cours
  est supprimé dans son propre bloc try/except afin qu'un seul échec n'interrompe
  pas l'ensemble du lot.

Toutes les opérations destructrices sont encapsulées dans ``transaction.atomic()`` et
journalisées au niveau d'audit CRITIQUE.

Voir aussi :
  ``views_admin_faculties.py``       — CRUD des facultés.
  ``views_admin_departments.py``     — CRUD des départements.
  ``views_admin_academic_years.py``  — CRUD des années académiques.
  ``views_admin_prerequisites.py``   — point d'API des prérequis.

Fait partie du tableau de bord UniAbsences.
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
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import CoursForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_courses(request):
    """
    Liste tous les cours et gère la création d'un nouveau cours.

    GET  — affiche une liste paginée des cours (20 par page, ordonnée par
           ``code_cours``) avec un ``CoursForm`` vide.
    POST — valide le formulaire et crée le cours ; journalise une entrée
           d'audit CRITIQUE et redirige vers la liste en cas de succès.

    Paramètres
    ----------
    request : HttpRequest
        Prend en charge le paramètre GET ``page`` pour la pagination.

    Retourne
    -------
    HttpResponse
        Template ``dashboard/admin_courses.html`` rendu en GET ou POST invalide,
        ou redirection vers ``admin_courses`` en cas de création réussie.
    """

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

    paginator = Paginator(courses, 20)
    courses_page = safe_get_page(paginator, request.GET.get("page"))

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
    """
    Modifie ou désactive un cours existant.

    GET  — affiche le formulaire d'édition prérempli avec les valeurs actuelles
           du cours.
    POST — valide et enregistre les modifications ; le message d'audit distingue
           une modification ordinaire d'une désactivation en fonction de ``cours.actif``.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    course_id : int
        Clé primaire du ``Cours`` à modifier.

    Retourne
    -------
    HttpResponse
        Template ``dashboard/admin_course_edit.html`` rendu en GET ou POST
        invalide, ou redirection vers ``admin_courses`` en cas de succès.
    """

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
    """
    Supprime un cours avec cascade complet des enregistrements dépendants.

    GET  — affiche une page de confirmation (``admin_confirm_delete.html``)
           listant les comptes d'objets dépendants qui seront également
           supprimés.
    POST — exécute la suppression en cascade dans une transaction :
           ``Justification → Absence → Inscription → Seance → Cours``.
           Les comptes sont pré-calculés avant la suppression pour le message d'audit.
           ``ProtectedError`` et les exceptions inattendues sont capturés et
           signalés via les messages Django sans planter la vue.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.
    course_id : int
        Clé primaire du ``Cours`` à supprimer.

    Retourne
    -------
    HttpResponse
        Page de confirmation en GET, ou redirection vers ``admin_courses``
        après POST (succès ou échec).
    """

    cours = get_object_or_404(Cours, id_cours=course_id)
    cours_code = cours.code_cours
    cours_nom = cours.nom_cours
    dept_nom = cours.id_departement.nom_departement

    inscriptions = Inscription.objects.filter(id_cours=cours)
    inscriptions_count = inscriptions.count()
    absences = Absence.objects.filter(id_inscription__in=inscriptions)
    absences_count = absences.count()
    justifications = Justification.objects.filter(id_absence__in=absences)
    justifications_count = justifications.count()
    seances = Seance.objects.filter(id_cours=cours)
    seances_count = seances.count()

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

    try:
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

        cascade_msg = (
            f" (suppression en cascade: {', '.join(cascade_info)})"
            if cascade_info
            else ""
        )

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
            f"Impossible de supprimer le cours '{cours_code}'. "
            f"Objets liés bloquants : {summary}. "
            f"Veuillez d'abord supprimer ou modifier ces éléments.",
        )
    except Exception:
        logger.exception("Erreur lors de la suppression du cours %s", cours_code)
        messages.error(
            request,
            f"Erreur lors de la suppression du cours '{cours_code}'. "
            f"Veuillez vérifier les dépendances ou contacter l'administrateur système.",
        )

    return redirect("dashboard:admin_courses")


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_courses_delete_multiple(request):
    """
    Supprime en masse une liste de cours soumis depuis la page de liste des cours.

    Lit les IDs de cours depuis la liste POST ``course_ids``, les dédoublonne et
    les valide, puis itère sur le queryset verrouillé en supprimant chaque
    cours (avec son cascade complet) individuellement. Un try/except par cours
    garantit qu'un échec n'empêche pas les autres cours d'être
    supprimés. Chaque suppression réussie est journalisée au niveau CRITIQUE.

    Paramètres
    ----------
    request : HttpRequest
        Le corps POST doit contenir une ou plusieurs valeurs ``course_ids``.

    Retourne
    -------
    HttpResponseRedirect
        Redirige toujours vers ``admin_courses`` avec des messages de succès
        et/ou d'erreur résumant le résultat.
    """

    raw_ids = request.POST.getlist("course_ids")
    if not raw_ids:
        messages.error(request, "Aucun cours sélectionné.")
        return redirect("dashboard:admin_courses")

    course_ids = []
    for raw_id in raw_ids:
        try:
            course_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    course_ids = list(dict.fromkeys(course_ids))

    if not course_ids:
        messages.error(request, "Aucun identifiant de cours valide reçu.")
        return redirect("dashboard:admin_courses")

    deleted_count = 0
    failed_names = []

    try:
        with transaction.atomic():
            courses_qs = Cours.objects.select_for_update().filter(id_cours__in=course_ids)
            courses_list = list(courses_qs)

            for cours in courses_list:
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

                    cascade_msg = (
                        f" (cascade: {', '.join(cascade_parts)})" if cascade_parts else ""
                    )

                    log_action(
                        request.user,
                        f"CRITIQUE: Suppression du cours '{cours.code_cours} - {cours.nom_cours}' "
                        f"(Département: {cours.id_departement.nom_departement}, ID: {cours.id_cours})"
                        f"{cascade_msg} - Suppression multiple",
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
        return redirect("dashboard:admin_courses")

    if deleted_count:
        messages.success(request, f"{deleted_count} cours supprimé(s) avec succès.")
    if failed_names:
        messages.error(
            request,
            f"Impossible de supprimer : {', '.join(failed_names)}. "
            f"Vérifiez les dépendances.",
        )

    return redirect("dashboard:admin_courses")
