"""
Vues CRUD des années académiques pour le tableau de bord administrateur UniAbsences.

Fournit des vues réservées aux administrateurs pour gérer les enregistrements ``AnneeAcademique`` :

- Lister toutes les années académiques et en créer de nouvelles via ``AnneeAcademiqueForm``.
- Promouvoir une année académique à l'état actif (exactement une année est active
  à un instant donné ; la méthode ``save()`` du formulaire désactive toutes les autres de
  façon atomique).
- Supprimer une année académique avec un cascade manuel complet : les inscriptions, absences,
  justifications et séances appartenant à cette année sont supprimées dans
  l'ordre des dépendances correct avant que l'année elle-même ne soit retirée.

Toutes les opérations d'écriture sont journalisées dans le journal d'audit au niveau CRITIQUE
car les modifications de l'année académique affectent l'ensemble du système.

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
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import AnneeAcademiqueForm
from apps.enrollments.models import Inscription

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_academic_years(request):
    """
    Liste toutes les années académiques et gère la création d'une nouvelle année.

    GET  — affiche la liste des années académiques avec un formulaire de création vide.
    POST — valide ``AnneeAcademiqueForm`` et crée la nouvelle année ;
           journalise une entrée d'audit CRITIQUE en cas de succès et redirige vers
           la liste.

    Paramètres
    ----------
    request : HttpRequest
        La requête HTTP entrante.

    Retourne
    -------
    HttpResponse
        Template ``dashboard/admin_academic_years.html`` rendu en GET
        ou POST invalide, ou redirection vers ``admin_academic_years`` en cas de
        création réussie.
    """
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
    """
    Marque l'année académique spécifiée comme active à l'échelle du système.

    Utilise ``select_for_update()`` dans une transaction pour éviter une condition
    de concurrence où deux administrateurs activent simultanément différentes années.
    La logique basée sur les signaux dans ``AnneeAcademique.save()`` du modèle gère
    la désactivation des autres années (la surcharge ``save()`` du formulaire fait de même
    via ``AnneeAcademiqueForm`` — ici nous définissons directement sur le modèle).

    Paramètres
    ----------
    request : HttpRequest
        Doit être une requête POST (imposé par ``@require_http_methods``).
    year_id : int
        Clé primaire de l'``AnneeAcademique`` à activer.

    Retourne
    -------
    HttpResponseRedirect
        Redirige toujours vers ``admin_academic_years``.
    """

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
    """
    Supprime une année académique et toutes ses données dépendantes.

    Effectue une suppression en cascade manuelle dans l'ordre des dépendances correct
    pour éviter les erreurs de contrainte de clé étrangère :
    ``Justification → Absence → Inscription / Seance → AnneeAcademique``.

    Garde-fous :
    - L'année actuellement active ne peut pas être supprimée ; l'administrateur doit
      d'abord activer une autre année.
    - ``ProtectedError`` provenant de contraintes ``PROTECT`` inattendues est capturé
      et signalé sans annuler un état indépendant.

    Paramètres
    ----------
    request : HttpRequest
        Doit être une requête POST.
    year_id : int
        Clé primaire de l'``AnneeAcademique`` à supprimer.

    Retourne
    -------
    HttpResponseRedirect
        Redirige toujours vers ``admin_academic_years``.
    """

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
