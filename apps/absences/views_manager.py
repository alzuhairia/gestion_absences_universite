from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.models import User
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

from .models import Absence, Justification

# Only allow current (non-legacy) types for new edits
_VALID_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}
_VALID_STATUTS = set(Absence.Statut.values)


def _get_seance_duration(seance):
    """Calculate session duration in hours from heure_debut/heure_fin.
    Returns (hours_float, 'HH:MM' string) or (None, None)."""
    if seance.heure_debut and seance.heure_fin:
        from datetime import datetime, date

        dt_debut = datetime.combine(date.today(), seance.heure_debut)
        dt_fin = datetime.combine(date.today(), seance.heure_fin)
        total_seconds = (dt_fin - dt_debut).seconds
        hours = round(total_seconds / 3600.0, 2)
        if hours > 0:
            h = total_seconds // 3600
            m = (total_seconds % 3600) // 60
            return hours, f"{h:02d}:{m:02d}"
    return None, None


@login_required
@secretary_required
@require_http_methods(["GET", "POST"])
def edit_absence(request, pk):
    absence = get_object_or_404(
        Absence.objects.select_related("id_seance"), pk=pk
    )

    if absence.statut == Absence.Statut.JUSTIFIEE:
        messages.error(
            request,
            "Cette absence est déjà justifiée et ne peut plus être modifiée. "
            "Veuillez d'abord changer son statut via le traitement des justificatifs.",
        )
        return redirect("absences:validation_list")

    seance_duration, seance_duration_display = _get_seance_duration(absence.id_seance)

    if request.method == "POST":
        ctx = {
            "absence": absence,
            "seance_duration": seance_duration,
            "seance_duration_display": seance_duration_display,
        }

        # --- Validate all inputs BEFORE any DB write ---
        reason = request.POST.get("reason", "").strip()
        new_type = request.POST.get("type_absence", "")
        new_statut = request.POST.get("statut", "")

        if not reason:
            messages.error(
                request,
                "Un motif est obligatoire pour modifier une absence. "
                "Veuillez indiquer la raison de cette modification.",
            )
            return render(request, "absences/edit_absence.html", ctx)

        if new_type not in _VALID_TYPES:
            messages.error(request, "Type d'absence invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        if new_statut not in _VALID_STATUTS:
            messages.error(request, "Statut invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        try:
            new_duree = float(request.POST.get("duree_absence") or 0)
        except (ValueError, TypeError):
            messages.error(
                request, "Durée invalide. Veuillez entrer un nombre décimal (ex : 1.5)."
            )
            return render(request, "absences/edit_absence.html", ctx)

        if new_duree <= 0:
            messages.error(request, "La durée doit être supérieure à zéro.")
            return render(request, "absences/edit_absence.html", ctx)

        # Validate duration does not exceed session duration
        if seance_duration and new_duree > seance_duration:
            messages.error(
                request,
                f"La durée d'absence ({new_duree}h) ne peut pas dépasser "
                f"la durée de la séance ({seance_duration}h).",
            )
            return render(request, "absences/edit_absence.html", ctx)

        with transaction.atomic():
            # Re-fetch with row lock to prevent concurrent modification (TOCTOU)
            # select_related prefetches FK chains used in log_action message below
            absence = (
                Absence.objects
                .select_related(
                    "id_seance__id_cours",
                    "id_inscription__id_etudiant",
                )
                .select_for_update()
                .get(pk=pk)
            )

            # Capture old state for audit comparison inside the lock
            old_statut = absence.statut
            old_duree = float(absence.duree_absence or 0)
            old_type = absence.type_absence

            # --- Detect changes ---
            change_desc = f"Absence {pk} UPDATED. "
            changed = False

            if old_statut != new_statut:
                change_desc += f"Statut: {old_statut} -> {new_statut}. "
                changed = True
            if old_duree != new_duree:
                change_desc += f"Durée: {old_duree} -> {new_duree}. "
                changed = True
            if old_type != new_type:
                change_desc += f"Type: {old_type} -> {new_type}. "
                changed = True

            if changed:
                change_desc += f"Motif: {reason}"

                absence.duree_absence = new_duree
                absence.type_absence = new_type
                absence.statut = new_statut
                absence.save()

                # Synchronize Justification.state with Absence.statut
                # to maintain a single source of truth across all roles
                if old_statut != new_statut:
                    justification = Justification.objects.filter(
                        id_absence=absence
                    ).first()
                    if justification:
                        if new_statut == Absence.Statut.JUSTIFIEE:
                            justification.state = Justification.State.ACCEPTEE
                        elif new_statut == Absence.Statut.NON_JUSTIFIEE:
                            justification.state = Justification.State.REFUSEE
                        elif new_statut == Absence.Statut.EN_ATTENTE:
                            justification.state = Justification.State.EN_ATTENTE
                        justification.save()

                log_action(
                    request.user,
                    f"Secrétaire a modifié l'absence {pk} pour "
                    f"{absence.id_inscription.id_etudiant.get_full_name()} - "
                    f"{absence.id_seance.id_cours.code_cours}. {change_desc}",
                    request,
                    niveau="WARNING",
                    objet_type="ABSENCE",
                    objet_id=pk,
                )

        if changed:
            messages.success(
                request,
                "L'absence a été modifiée avec succès. "
                "La modification a été enregistrée dans le journal d'audit avec le motif indiqué.",
            )
        else:
            messages.info(request, "Aucune modification détectée.")

        return redirect("absences:validation_list")

    return render(
        request,
        "absences/edit_absence.html",
        {
            "absence": absence,
            "seance_duration": seance_duration,
            "seance_duration_display": seance_duration_display,
        },
    )
