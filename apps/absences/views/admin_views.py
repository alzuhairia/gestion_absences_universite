"""
Admin / secretary direct-edit views — apps/absences/views/admin_views.py

Provides the secretariat with the ability to directly modify an existing
absence record (type, status, duration) while enforcing a mandatory audit
reason.  Every change is written to the audit log via ``log_action``.

Key design decisions
--------------------
- ``_VALID_TYPES`` and ``_VALID_STATUTS`` are module-level constants so that
  validation logic does not construct new sets on every request.
- ``select_for_update()`` inside the transaction prevents a TOCTOU race
  condition where two secretaries could edit the same record simultaneously.
- The ``Justification`` state machine is kept in sync whenever the absence
  status changes, so the two models never diverge.
- Emails are deliberately *not* sent here; the secretary is making an
  administrative correction, not responding to a student submission.

Security controls
-----------------
- ``@secretary_required`` — only the secretariat role may access this view.
- ``select_for_update()`` — row-level lock prevents concurrent edits.
- Full model validation and whitelist checks run before any DB write.

Part of the UniAbsences absences system.
"""
import logging
from decimal import Decimal, ROUND_HALF_UP

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required

from ..models import Absence, Justification

logger = logging.getLogger(__name__)

# Whitelist of absence types that the secretary is permitted to set directly.
_VALID_TYPES = {Absence.TypeAbsence.ABSENT, Absence.TypeAbsence.PARTIEL}

# Whitelist of all valid absence status values, derived from the model enum.
_VALID_STATUTS = set(Absence.Statut.values)


def _get_seance_duration(seance):
    """
    Calculate the duration of a session in decimal hours for display and validation.

    Combines ``heure_debut`` and ``heure_fin`` with an arbitrary date so that
    Python's ``timedelta`` arithmetic can be applied to ``time`` objects.

    Parameters
    ----------
    seance : Seance
        The session whose start/end times are inspected.

    Returns
    -------
    tuple[float | None, str | None]
        A ``(decimal_hours, "HH:MM")`` pair, or ``(None, None)`` when the
        session has no valid time range.
    """
    if seance.heure_debut and seance.heure_fin:
        from datetime import datetime, date
        # Use an arbitrary date so we can subtract two time objects via datetime.
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
    """
    Allow the secretariat to directly modify an existing absence record.

    A non-empty reason (``reason``) is mandatory for every change; the
    motivation is written to the audit log so that any modification is fully
    traceable.

    GET
        Render the edit form pre-populated with the current absence values and
        the computed session duration for reference.

    POST
        Validate all submitted fields, acquire a row-level lock, apply changes
        atomically, keep the ``Justification`` state machine in sync, write an
        audit entry, and redirect to the validation list.

    Business rules enforced
    -----------------------
    - An absence with status ``JUSTIFIEE`` cannot be edited directly; the
      secretary must first change its status through the justification workflow.
    - The new duration must be positive and must not exceed the session duration.
    - Type and status values are validated against server-side whitelists.

    Parameters
    ----------
    request : HttpRequest
        The incoming HTTP request.
    pk : int
        Primary key of the ``Absence`` record to edit.

    Returns
    -------
    HttpResponse
        Rendered form on GET or validation error, redirect on success.

    Raises
    ------
    Http404
        When no ``Absence`` with the given ``pk`` exists.
    """
    absence = get_object_or_404(Absence.objects.select_related("id_seance"), pk=pk)

    # Prevent direct edits to already-justified absences; those must go through
    # the justification workflow to preserve the audit trail.
    if absence.statut == Absence.Statut.JUSTIFIEE:
        messages.error(
            request,
            "Cette absence est déjà justifiée et ne peut plus être modifiée. "
            "Veuillez d'abord changer son statut via le traitement des justificatifs.",
        )
        return redirect("absences:validation_list")

    # Pre-compute session duration so the form can display it as a ceiling value.
    seance_duration, seance_duration_display = _get_seance_duration(absence.id_seance)

    if request.method == "POST":
        # Bundle context early so every early-return path can re-render the form.
        ctx = {
            "absence": absence,
            "seance_duration": seance_duration,
            "seance_duration_display": seance_duration_display,
        }

        reason = request.POST.get("reason", "").strip()
        new_type = request.POST.get("type_absence", "")
        new_statut = request.POST.get("statut", "")

        # Reason is mandatory — reject silently submitting with no justification.
        if not reason:
            messages.error(request, "Un motif est obligatoire pour modifier une absence.")
            return render(request, "absences/edit_absence.html", ctx)

        # Validate type against the server-side whitelist (not just the form widget).
        if new_type not in _VALID_TYPES:
            messages.error(request, "Type d'absence invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        # Validate status against all known enum values.
        if new_statut not in _VALID_STATUTS:
            messages.error(request, "Statut invalide.")
            return render(request, "absences/edit_absence.html", ctx)

        # Parse and quantize the duration to exactly 2 decimal places.
        try:
            raw_duree = request.POST.get("duree_absence") or "0"
            new_duree = Decimal(str(raw_duree)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        except (ValueError, TypeError, ArithmeticError):
            messages.error(request, "Durée invalide (ex : 1.5).")
            return render(request, "absences/edit_absence.html", ctx)

        if new_duree <= 0:
            messages.error(request, "La durée doit être supérieure à zéro.")
            return render(request, "absences/edit_absence.html", ctx)

        # Ensure the declared duration does not exceed the actual session length.
        if seance_duration and new_duree > seance_duration:
            messages.error(
                request,
                f"La durée ({new_duree}h) ne peut pas dépasser la durée de la séance ({seance_duration}h).",
            )
            return render(request, "absences/edit_absence.html", ctx)

        with transaction.atomic():
            # Re-fetch with select_for_update to hold a row-level lock for the
            # duration of the transaction and prevent concurrent double-edits.
            absence = (
                Absence.objects
                .select_related("id_seance__id_cours", "id_inscription__id_etudiant")
                .select_for_update()
                .get(pk=pk)
            )

            # Another secretary may have justified this absence between our GET
            # and this POST — check again inside the transaction.
            if absence.statut == Absence.Statut.JUSTIFIEE:
                messages.error(request, "Cette absence a été justifiée entre-temps et ne peut plus être modifiée.")
                return redirect("absences:validation_list")

            # Capture old values to build a diff for the audit log.
            old_statut = absence.statut
            old_duree = float(absence.duree_absence or 0)
            old_type = absence.type_absence

            change_desc = f"Absence {pk} UPDATED. "
            changed = False

            # Build a human-readable diff description for each changed field.
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

                # Keep the Justification state machine in sync whenever the
                # parent Absence status changes, so both models remain consistent.
                if old_statut != new_statut:
                    justification = Justification.objects.filter(id_absence=absence).first()
                    if justification:
                        if new_statut == Absence.Statut.JUSTIFIEE:
                            # Secretary is manually marking as justified.
                            justification.state = Justification.State.ACCEPTEE
                            justification.validee_par = request.user
                            justification.date_validation = timezone.now()
                        elif new_statut == Absence.Statut.NON_JUSTIFIEE:
                            # Secretary is explicitly rejecting the justification.
                            justification.state = Justification.State.REFUSEE
                            justification.validee_par = request.user
                            justification.date_validation = timezone.now()
                        elif new_statut == Absence.Statut.EN_ATTENTE:
                            # Reset to pending so the student can re-submit.
                            justification.state = Justification.State.EN_ATTENTE
                            justification.validee_par = None
                            justification.date_validation = None
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
            messages.success(request, "L'absence a été modifiée. La modification est enregistrée dans l'audit.")
        else:
            messages.info(request, "Aucune modification détectée.")

        return redirect("absences:validation_list")

    # GET — render the form with the current values.
    return render(request, "absences/edit_absence.html", {
        "absence": absence,
        "seance_duration": seance_duration,
        "seance_duration_display": seance_duration_display,
    })
