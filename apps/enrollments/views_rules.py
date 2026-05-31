"""
Views for absence threshold rules and enrollment exemption management.

This module gives the secretariat two capabilities:

1. ``rules_management`` — displays a paginated list of enrollments where
   the student's unjustified absence rate meets or exceeds the course (or
   system) threshold.  Each row shows whether the student is blocked from
   the exam or is currently protected by an active exemption.

2. ``toggle_exemption`` — grants or revokes the 40% exemption on a specific
   enrollment. Granting requires a written justification (motif). When an
   exemption is granted, the student receives an email notification and the
   action is recorded in the audit log.

Security: both views require ``@secretary_required``.

Belongs to: UniAbsences — enrollments app.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction

from apps.utils import safe_get_page
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.absences.models import Absence
from apps.absences.services import get_system_threshold, recalculer_eligibilite
from apps.audits.utils import log_action
from apps.dashboard.decorators import secretary_required
from apps.enrollments.models import Inscription
from apps.notifications.email import send_with_dedup


@login_required
@secretary_required
@require_GET
def rules_management(request):
    """
    Display enrollments where students are at or over the absence threshold.

    Only enrollments with status ``EN_COURS`` for the currently active
    academic year are evaluated. For each such enrollment the view computes:

    - Total unjustified, past-session absence hours (NON_JUSTIFIEE only —
      absences with status EN_ATTENTE are excluded so that pending
      justifications do not incorrectly flag a student as blocked).
    - The absence rate as a percentage of the course's total period count.
    - The effective threshold (course-level ``seuil_absence`` if set,
      otherwise the system default returned by ``get_system_threshold()``).
    - Whether an exemption is active and its effective margin.

    Enrollments are included in the ``at_risk_list`` only when the raw rate
    equals or exceeds the base threshold (even if an exemption raises the
    effective blocking threshold above the current rate).

    Parameters
    ----------
    request : HttpRequest
        Must be authenticated as a secretary (GET only).

    Returns
    -------
    HttpResponse
        Renders ``enrollments/rules_list.html`` with context:
          - ``at_risk_list``    — paginated list of risk-assessment dicts
          - ``page_obj``        — pagination object
          - ``blocked_count``   — number of students fully blocked from exams
          - ``exempted_count``  — number of students whose exemption is keeping
                                  them below the effective blocking threshold
    """
    from apps.academic_sessions.models import AnneeAcademique

    active_year = AnneeAcademique.objects.filter(active=True).first()
    system_threshold = get_system_threshold()

    # Fetch all active-year, in-progress enrollments with course and student data.
    inscriptions_qs = Inscription.objects.filter(
        status=Inscription.Status.EN_COURS,
    ).select_related("id_cours", "id_etudiant")
    if active_year:
        inscriptions_qs = inscriptions_qs.filter(id_annee=active_year)

    # Materialise into a list once so we can iterate twice (IDs + loop) without
    # hitting the database twice.
    inscriptions_list = list(inscriptions_qs)
    inscription_ids = [ins.id_inscription for ins in inscriptions_list]

    # Aggregate unjustified absence hours per enrollment in a single query.
    # Strictly NON_JUSTIFIEE only — excluding EN_ATTENTE ensures that a student
    # whose justification is still under review is not incorrectly penalised.
    today = timezone.localdate()
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,  # Only past sessions count.
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )
    at_risk_list = []

    for ins in inscriptions_list:
        cours = ins.id_cours
        if cours.nombre_total_periodes > 0:
            total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)

            # Compute the raw absence rate for this enrollment.
            rate = (total_abs / cours.nombre_total_periodes) * 100

            # Use the course-specific threshold if defined; fall back to system default.
            seuil = (
                cours.seuil_absence
                if cours.seuil_absence is not None
                else system_threshold
            )

            # The effective threshold is raised by exemption_margin when exemption
            # is active, capped at 100% to avoid nonsensical values.
            seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

            # Include the enrollment only when the raw rate reaches the base threshold.
            if rate >= seuil:
                is_blocked = rate >= seuil_effectif
                # Under exemption = rate exceeds base seuil but not the raised effective seuil.
                is_under_exemption = ins.exemption_40 and not is_blocked
                at_risk_list.append(
                    {
                        "inscription": ins,
                        "etudiant": ins.id_etudiant,
                        "cours": cours,
                        "total_abs": total_abs,
                        "rate": round(rate, 1),
                        "seuil": seuil,
                        "seuil_effectif": seuil_effectif,
                        "is_blocked": is_blocked,
                        "is_under_exemption": is_under_exemption,
                        "exemption": ins.exemption_40,
                        "exemption_margin": ins.exemption_margin,
                    }
                )

    # Summary statistics for the page header badges.
    blocked_count = sum(1 for item in at_risk_list if item["is_blocked"])
    exempted_count = sum(1 for item in at_risk_list if item["is_under_exemption"])

    # Paginate at 25 rows per page.
    paginator = Paginator(at_risk_list, 25)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "enrollments/rules_list.html",
        {
            "at_risk_list": page_obj,
            "page_obj": page_obj,
            "blocked_count": blocked_count,
            "exempted_count": exempted_count,
        },
    )


@login_required
@secretary_required
@require_POST
def toggle_exemption(request, pk):
    """
    Grant or revoke the absence threshold exemption for an enrollment.

    The ``action`` POST parameter drives the operation:
      - ``"grant"`` — sets ``exemption_40=True`` with the provided motif and
        margin, recalculates exam eligibility, sends an email to the student,
        and logs the action at WARNING audit level.
      - ``"revoke"`` — clears the exemption, recalculates exam eligibility,
        and logs the action at WARNING audit level.

    The enrollment record is locked with ``select_for_update()`` inside an
    atomic transaction to prevent race conditions when two secretaries act on
    the same enrollment simultaneously.

    The student email is dispatched via ``send_with_dedup`` registered as an
    ``on_commit`` callback so the email is only sent if the transaction commits
    successfully.

    Parameters
    ----------
    request : HttpRequest
        POST parameters:
          - ``action``           (str) — ``"grant"`` or ``"revoke"``
          - ``motif``            (str) — required when action is ``"grant"``
          - ``exemption_margin`` (int, optional) — additional threshold
            percentage points (default 10, clamped to [1, 100])
    pk : int
        Primary key of the ``Inscription`` to modify.

    Returns
    -------
    HttpResponseRedirect
        Always redirects to ``dashboard:secretary_seuils_absence``.
    """
    # Verify the enrollment exists before acquiring any locks.
    get_object_or_404(Inscription, pk=pk)

    action = request.POST.get("action")  # Expected: 'grant' or 'revoke'
    motif = request.POST.get("motif", "").strip()

    if action == "grant":
        # A written justification is mandatory for audit and legal traceability.
        if not motif:
            messages.error(request, "Un motif est requis pour accorder une exemption.")
            return redirect("dashboard:secretary_seuils_absence")
        if len(motif) > 2000:
            messages.error(request, "Le motif ne peut pas dépasser 2000 caractères.")
            return redirect("dashboard:secretary_seuils_absence")

        # Parse the margin; default to 10 percentage points, clamp to [1, 100].
        try:
            margin = int(request.POST.get("exemption_margin", 10))
        except (ValueError, TypeError):
            margin = 10
        margin = max(1, min(margin, 100))

        with transaction.atomic():
            # Lock the row to prevent a concurrent revoke/grant from another session.
            inscription = (
                Inscription.objects
                .select_related("id_etudiant", "id_cours")
                .select_for_update()
                .get(pk=pk)
            )
            inscription.exemption_40 = True
            inscription.motif_exemption = motif
            inscription.exemption_margin = margin
            inscription.save()

            # Recalculate the eligible_examen flag with the new effective threshold.
            recalculer_eligibilite(inscription)

            log_action(
                request.user,
                f"Secrétaire a accordé une EXEMPTION à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. Motif: {motif[:200]}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )

            # Build the notification email parameters while still inside the
            # transaction so the FK data is still locked and consistent.
            student = inscription.id_etudiant
            course_name = inscription.id_cours.nom_cours
            insc_pk = inscription.id_inscription
            subject = f"[UniAbsences] Exemption accordée — {course_name}"
            body = (
                f"Bonjour {student.get_full_name()},\n\n"
                f"Une exemption au seuil d'absence a été accordée pour le cours "
                f"« {course_name} ».\n\n"
                f"Vous êtes désormais autorisé(e) à passer l'examen malgré le "
                f"dépassement du seuil d'absence.\n\n"
                f"— UniAbsences Notification System"
            )
            # Defer the email send until after the transaction commits to avoid
            # sending a notification for a transaction that may roll back.
            transaction.on_commit(lambda: send_with_dedup(
                student, subject, body, None,
                event_type="exemption_granted",
                event_key=str(insc_pk),
            ))

        messages.success(
            request,
            f"L'exemption a été accordée avec succès à {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant peut maintenant passer les examens malgré le dépassement du seuil.",
        )

    elif action != "revoke":
        # Any action other than 'grant' or 'revoke' is invalid.
        messages.error(request, "Action invalide.")
        return redirect("dashboard:secretary_seuils_absence")

    if action == "revoke":
        with transaction.atomic():
            inscription = (
                Inscription.objects
                .select_related("id_etudiant", "id_cours")
                .select_for_update()
                .get(pk=pk)
            )
            inscription.exemption_40 = False
            inscription.motif_exemption = None
            inscription.save()

            # Recalculate eligibility with the exemption removed — the student
            # may now fall below the exam eligibility threshold.
            recalculer_eligibilite(inscription)

            log_action(
                request.user,
                f"Secrétaire a RÉVOQUÉ l'exemption de {inscription.id_etudiant.get_full_name()} pour le cours {inscription.id_cours.code_cours}",
                request,
                niveau="WARNING",
                objet_type="INSCRIPTION",
                objet_id=inscription.id_inscription,
            )
        messages.warning(
            request,
            f"L'exemption a été révoquée pour {inscription.id_etudiant.get_full_name()} dans le cours {inscription.id_cours.code_cours}. "
            f"L'étudiant est maintenant bloqué pour les examens.",
        )

    return redirect("dashboard:secretary_seuils_absence")
