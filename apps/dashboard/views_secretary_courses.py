"""
Vues CRUD des cours pour le tableau de bord secrétaire UniAbsences.

Ce module fournit au secrétaire la capacité de gérer les cours : les lister,
en créer de nouveaux, modifier ou désactiver ceux existants et les supprimer
(individuellement ou en masse) avec toutes leurs données dépendantes.

Vues
-----
``secretary_courses``
    GET  — liste paginée de tous les cours avec un formulaire de création.
    POST — crée un nouveau ``Cours`` ; journalise une entrée d'audit CRITIQUE en cas de succès.

``secretary_course_edit``
    GET  — affiche le formulaire d'édition prérempli avec les valeurs actuelles du cours.
    POST — enregistre les modifications ; journalise une entrée d'audit CRITIQUE en cas de succès.

``secretary_course_delete``
    POST — supprime un cours unique et supprime en cascade tous les enregistrements
           ``Seance``, ``Inscription``, ``Absence`` et ``Justification`` liés dans une
           seule transaction de base de données. Journalise une entrée d'audit CRITIQUE en cas de succès.

``secretary_courses_delete_multiple``
    POST — suppression en masse des cours identifiés par la liste de paramètres POST
           ``course_ids``. Chaque cours est supprimé individuellement dans une transaction
           atomique partagée afin que l'ensemble du lot échoue ou réussisse ensemble.
           Journalise une entrée d'audit CRITIQUE par cours supprimé.

Toutes les vues de suppression gèrent ``ProtectedError`` (contrainte ``PROTECT`` de Django) et
les exceptions inattendues avec élégance, en affichant des messages flash descriptifs au lieu
d'erreurs 500 non gérées.

L'accès est réservé aux utilisateurs administrateurs/secrétaires authentifiés via
``@secretary_required``.

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
from apps.dashboard.decorators import secretary_required
from apps.dashboard.forms_admin import CoursForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_courses(request):
    """
    Liste tous les cours et gère la création d'un nouveau cours.

    GET
        Affiche la liste paginée des cours (20 par page) avec un
        ``CoursForm`` vide.

    POST
        Valide le formulaire soumis. En cas de succès, enregistre le nouveau cours, écrit
        une entrée d'audit CRITIQUE, affiche un message flash de succès et redirige
        en arrière.

    Paramètres
    ----------
    request : HttpRequest
        GET ou POST d'un utilisateur secrétaire/administrateur authentifié.

    Retourne
    -------
    HttpResponse
        Affiche ``dashboard/secretary_courses.html`` avec ``courses`` (paginé)
        et ``form``.
    """
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
    """
    Modifie ou désactive un cours existant.

    GET
        Affiche ``CoursForm`` prérempli avec les valeurs actuelles du cours.
        Passe également un booléen indiquant si le champ des prérequis dispose
        d'options sélectionnables (utilisé pour afficher/masquer conditionnellement ce groupe de champs).

    POST
        Valide et enregistre le cours mis à jour. Journalise si le cours a été
        « modifié » ou « désactivé » (en fonction du drapeau ``actif`` après l'enregistrement).

    Paramètres
    ----------
    request : HttpRequest
        GET ou POST d'un utilisateur secrétaire/administrateur authentifié.
    course_id : int
        Clé primaire du ``Cours`` à modifier.

    Retourne
    -------
    HttpResponse
        En GET ou POST invalide : affiche ``dashboard/secretary_course_edit.html``.
        En POST valide : redirige vers ``dashboard:secretary_courses``.
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

    # Informer le template si la liste déroulante des prérequis dispose de choix.
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
    """
    Supprime un cours unique et tous ses enregistrements dépendants.

    Les enregistrements dépendants sont supprimés explicitement dans l'ordre des dépendances dans une
    seule transaction atomique :
        1. Justifications  (référencent Absences)
        2. Absences        (référencent Inscriptions)
        3. Inscriptions    (référencent Cours)
        4. Seances         (référencent Cours)
        5. Cours

    Une entrée d'audit CRITIQUE est écrite après une suppression réussie.

    Gestion des erreurs
    -------------------
    - ``ProtectedError`` — objets liés protégés par la contrainte ``PROTECT`` ;
      un résumé descriptif est affiché à l'utilisateur.
    - Toute autre exception — journalisée au niveau ERROR ; un message d'erreur générique est
      affiché.

    Paramètres
    ----------
    request : HttpRequest
        POST d'un utilisateur secrétaire/administrateur authentifié.
    course_id : int
        Clé primaire du ``Cours`` à supprimer.

    Retourne
    -------
    HttpResponseRedirect
        Redirige vers ``dashboard:secretary_courses`` dans tous les cas.
    """
    cours = get_object_or_404(Cours, id_cours=course_id)
    cours_code = cours.code_cours
    cours_nom = cours.nom_cours
    dept_nom = cours.id_departement.nom_departement

    try:
        # Collecter les comptes du cascade avant suppression pour les inclure dans le message de succès.
        inscriptions = Inscription.objects.filter(id_cours=cours)
        inscriptions_count = inscriptions.count()
        absences = Absence.objects.filter(id_inscription__in=inscriptions)
        absences_count = absences.count()
        justifications = Justification.objects.filter(id_absence__in=absences)
        justifications_count = justifications.count()
        seances = Seance.objects.filter(id_cours=cours)
        seances_count = seances.count()

        with transaction.atomic():
            # Supprimer dans l'ordre des dépendances pour satisfaire les contraintes de clé étrangère.
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
        # Grouper les objets protégés par leur verbose_name de modèle pour un résumé concis.
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
    """
    Supprime en masse un ensemble de cours identifiés par le champ POST ``course_ids``.

    La vue lit la liste d'IDs depuis ``request.POST.getlist("course_ids")``,
    valide chacun comme un entier, les dédoublonne, puis supprime chaque
    cours (et ses dépendants) dans un seul bloc de transaction atomique.

    Chaque cours supprimé avec succès est journalisé comme une entrée d'audit CRITIQUE.
    Les cours qui échouent à la suppression (par exemple, exceptions inattendues) sont collectés et
    signalés dans un message flash d'erreur ; la transaction atomique annule
    l'ensemble du lot si une exception de niveau externe survient.

    Paramètres
    ----------
    request : HttpRequest
        POST d'un utilisateur secrétaire/administrateur authentifié. Doit inclure au moins
        un entier valide dans la liste ``course_ids``.

    Retourne
    -------
    HttpResponseRedirect
        Redirige vers ``dashboard:secretary_courses`` dans tous les cas.
    """
    raw_ids = request.POST.getlist("course_ids")
    if not raw_ids:
        messages.error(request, "Aucun cours sélectionné.")
        return redirect("dashboard:secretary_courses")

    # Analyser et dédoublonner les IDs ; ignorer silencieusement les valeurs non entières.
    course_ids = []
    for raw_id in raw_ids:
        try:
            course_ids.append(int(raw_id))
        except (TypeError, ValueError):
            continue
    # dict.fromkeys préserve l'ordre d'insertion tout en supprimant les doublons.
    course_ids = list(dict.fromkeys(course_ids))

    if not course_ids:
        messages.error(request, "Aucun identifiant de cours valide reçu.")
        return redirect("dashboard:secretary_courses")

    deleted_count = 0
    failed_names = []

    try:
        with transaction.atomic():
            # Verrouiller les lignes de cours sélectionnées pour empêcher les modifications concurrentes.
            courses_qs = Cours.objects.select_for_update().filter(id_cours__in=course_ids)
            for cours in list(courses_qs):
                try:
                    # Collecter les enregistrements dépendants pour ce cours.
                    inscriptions = Inscription.objects.filter(id_cours=cours)
                    absences = Absence.objects.filter(id_inscription__in=inscriptions)
                    justifications = Justification.objects.filter(id_absence__in=absences)
                    seances = Seance.objects.filter(id_cours=cours)

                    # Enregistrer les comptes pour le message du journal d'audit.
                    cascade_parts = []
                    jc = justifications.count()
                    ac = absences.count()
                    ic = inscriptions.count()
                    sc = seances.count()

                    # Supprimer dans l'ordre des dépendances.
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
