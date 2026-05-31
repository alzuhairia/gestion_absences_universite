"""
Vues CRUD des années académiques pour le tableau de bord secrétaire UniAbsences.

Ce module fournit au secrétaire la capacité de gérer les années académiques :
les lister, en créer de nouvelles, en désigner une comme active et supprimer les
années non actives avec toutes leurs données dépendantes.

Vues
-----
``secretary_academic_years``
    GET  — affiche la liste des années académiques avec un formulaire de création.
    POST — valide et enregistre une nouvelle ``AnneeAcademique`` ; journalise une
           entrée d'audit CRITIQUE en cas de succès.

``secretary_academic_year_set_active``
    POST — efface atomiquement le drapeau ``active`` sur toutes les années et le définit sur
           l'année choisie. Journalisé comme CRITIQUE.

``secretary_academic_year_delete``
    POST — supprime une année académique non active et supprime en cascade tous les
           enregistrements ``Inscription``, ``Absence``, ``Justification`` et ``Seance``
           liés dans une seule transaction de base de données. Bloqué lorsque
           l'année cible est actuellement active. Journalise à la fois les détails du cascade et
           la suppression elle-même comme CRITIQUE.

Toutes les vues sont réservées aux utilisateurs administrateurs/secrétaires authentifiés via
``@secretary_required``.

Fait partie du tableau de bord UniAbsences.
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
from apps.dashboard.decorators import secretary_required
from apps.dashboard.forms_admin import AnneeAcademiqueForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def secretary_academic_years(request):
    """
    Liste toutes les années académiques et gère la création d'une nouvelle.

    GET
        Affiche la liste des années académiques avec un ``AnneeAcademiqueForm`` vide.

    POST
        Valide le formulaire soumis. En cas de succès, enregistre la nouvelle année, écrit une
        entrée d'audit CRITIQUE, affiche un message flash de succès et redirige vers
        la même page. En cas d'échec, réaffiche le formulaire avec les erreurs de validation.

    Paramètres
    ----------
    request : HttpRequest
        GET ou POST d'un utilisateur secrétaire/administrateur authentifié.

    Retourne
    -------
    HttpResponse
        Affiche ``dashboard/secretary_academic_years.html`` avec ``years``
        (ordonné par libellé décroissant) et ``form``.
    """
    if request.method == "POST":
        form = AnneeAcademiqueForm(request.POST)
        if form.is_valid():
            year = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création de l'année académique '{year.libelle}' (Gestion structure académique - Secrétaire)",
                request,
                niveau="CRITIQUE",
                objet_type="AUTRE",
                objet_id=year.id_annee,
            )
            messages.success(request, f"Année académique '{year.libelle}' créée avec succès.")
            return redirect("dashboard:secretary_academic_years")
    else:
        form = AnneeAcademiqueForm()

    years = AnneeAcademique.objects.all().order_by("-libelle")

    return render(
        request,
        "dashboard/secretary_academic_years.html",
        {"years": years, "form": form},
    )


@login_required
@secretary_required
@require_http_methods(["POST"])
def secretary_academic_year_set_active(request, year_id):
    """
    Désigne atomiquement une année académique spécifique comme année active.

    Toutes les autres années sont désactivées dans la même transaction de base de données afin
    qu'exactement une année soit toujours active. L'opération est journalisée comme CRITIQUE.

    Paramètres
    ----------
    request : HttpRequest
        POST d'un utilisateur secrétaire/administrateur authentifié.
    year_id : int
        Clé primaire de l'``AnneeAcademique`` à activer.

    Retourne
    -------
    HttpResponseRedirect
        Redirige vers ``dashboard:secretary_academic_years``.
    """
    year = get_object_or_404(AnneeAcademique, id_annee=year_id)

    with transaction.atomic():
        # Désactiver toutes les années d'abord, puis activer l'année sélectionnée.
        AnneeAcademique.objects.update(active=False)
        year.active = True
        year.save()

    log_action(
        request.user,
        f"CRITIQUE: Année académique '{year.libelle}' définie comme active (Gestion structure académique - Secrétaire)",
        request,
        niveau="CRITIQUE",
        objet_type="AUTRE",
        objet_id=year.id_annee,
    )
    messages.success(request, f"Année académique '{year.libelle}' définie comme active.")

    return redirect("dashboard:secretary_academic_years")


@login_required
@secretary_required
@require_http_methods(["POST"])
def secretary_academic_year_delete(request, year_id):
    """
    Supprime une année académique non active et tous ses enregistrements dépendants.

    La suppression est effectuée dans un seul bloc ``transaction.atomic``.
    Les enregistrements dépendants sont supprimés explicitement dans l'ordre des dépendances pour éviter
    les violations de contrainte d'intégrité :
        1. Justifications  (référencent Absences)
        2. Absences        (référencent Inscriptions)
        3. Inscriptions    (référencent AnneeAcademique)
        4. Seances         (référencent AnneeAcademique)
        5. AnneeAcademique

    Cas bloqués
    -----------
    - L'année cible est actuellement marquée ``active`` : un message d'erreur est affiché
      et l'utilisateur est redirigé sans suppression.

    Gestion des erreurs
    -------------------
    - ``ProtectedError`` — un ou plusieurs objets liés sont protégés par la contrainte
      de suppression ``PROTECT`` de Django ; un message d'erreur descriptif est affiché.
    - Toute autre exception — journalisée au niveau ERROR ; un message d'erreur générique est
      affiché à l'utilisateur.

    Paramètres
    ----------
    request : HttpRequest
        POST d'un utilisateur secrétaire/administrateur authentifié.
    year_id : int
        Clé primaire de l'``AnneeAcademique`` à supprimer.

    Retourne
    -------
    HttpResponseRedirect
        Redirige vers ``dashboard:secretary_academic_years`` dans tous les cas.
    """
    year = get_object_or_404(AnneeAcademique, id_annee=year_id)
    year_libelle = year.libelle

    try:
        with transaction.atomic():
            # Verrouiller la ligne pour empêcher les modifications concurrentes pendant la suppression.
            year = AnneeAcademique.objects.select_for_update().get(id_annee=year_id)

            # Garde-fou : refuser la suppression de l'année active pour éviter la perte de données.
            if year.active:
                messages.error(
                    request,
                    f"Impossible de supprimer l'année académique '{year_libelle}' car elle est actuellement active. "
                    f"Veuillez d'abord définir une autre année comme active.",
                )
                return redirect("dashboard:secretary_academic_years")

            # Collecter les comptes du cascade avant suppression pour le message de succès.
            inscriptions = Inscription.objects.filter(id_annee=year)
            inscriptions_count = inscriptions.count()
            absences = Absence.objects.filter(id_inscription__in=inscriptions)
            absences_count = absences.count()
            justifications = Justification.objects.filter(id_absence__in=absences)
            justifications_count = justifications.count()
            seances = Seance.objects.filter(id_annee=year)
            seances_count = seances.count()

            # Supprimer dans l'ordre des dépendances pour satisfaire les contraintes de clé étrangère.
            justifications.delete()
            absences.delete()
            inscriptions.delete()
            seances.delete()
            year.delete()

        # Construire un résumé lisible de ce qui a été supprimé en cascade.
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
            f"CRITIQUE: Suppression de l'année académique '{year_libelle}' (ID: {year_id}) - Gestion structure académique - Secrétaire",
            request,
            niveau="CRITIQUE",
            objet_type="AUTRE",
            objet_id=year_id,
        )
        success_msg = f"Année académique '{year_libelle}' supprimée avec succès."
        if cascade_info:
            success_msg += f" Suppression en cascade effectuée : {', '.join(cascade_info)}."
        messages.success(request, success_msg)

    except ProtectedError as e:
        # Django lève ProtectedError lorsqu'un objet lié utilise on_delete=PROTECT.
        protected_objects = [str(obj) for obj in e.protected_objects]
        logger.error(f"ProtectedError lors de la suppression de l'année académique {year_libelle}: {e}")
        messages.error(
            request,
            f"Impossible de supprimer l'année académique '{year_libelle}'. "
            f"Dépendances trouvées : {', '.join(protected_objects)}.",
        )
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de l'année académique {year_libelle}: {e}", exc_info=True)
        messages.error(request, f"Erreur lors de la suppression de l'année académique '{year_libelle}'.")

    return redirect("dashboard:secretary_academic_years")
