"""
Exam Eligibility & Risk Calculation Service — apps/absences/services/eligibility_service.py

Part of the UniAbsences university attendance management system.

This module is the authoritative source of truth for exam eligibility and
absence-risk status across the entire system.  Any view, signal, or API
endpoint that needs to determine whether a student is blocked from sitting
an exam must call the functions here rather than duplicating the logic.

Main responsibilities:
  - ``recalculer_eligibilite``         : decide (and persist) whether a student is blocked
  - ``calculer_risque_inscription``    : return the full risk profile for one enrolment
  - ``get_at_risk_count_for_queryset`` : bulk count of at-risk enrolments for dashboards

Central business rule:
  A student is blocked if their NON_JUSTIFIEE absence rate >= the effective threshold.

  Effective threshold = course threshold + exemption margin
      (if an exemption has been granted to the student; otherwise = course threshold).

Triggered automatically:
  ``recalculer_eligibilite`` is called by the ``post_save`` signal on ``Absence``
  so that every absence creation or update immediately re-evaluates eligibility.
"""
import logging

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.audits.models import LogAudit
from apps.notifications.email import (
    build_eligibility_restored_email,
    build_threshold_exceeded_email,
    build_threshold_exceeded_professor_email,
    send_notification_email,
)
from apps.notifications.models import Notification

from ..models import Absence
from .absence_service import calculer_absence_stats

logger = logging.getLogger(__name__)


def get_system_threshold():
    """
    Retrieve the system-wide default absence threshold from ``SystemSettings``.

    This is used as a fallback when a course has no per-course threshold
    configured.  The value is fetched in a single database query.

    Returns:
        int | float: default absence threshold percentage (e.g. 20).
    """
    from apps.dashboard.models import SystemSettings

    return SystemSettings.get_settings().default_absence_threshold


def recalculer_eligibilite(inscription):
    """
    Recalculate and persist the exam eligibility status for one enrolment.

    This is the core decision function of the UniAbsences system.

    Algorithm:
      1. Compute the current absence statistics via ``calculer_absence_stats``.
      2. Determine the effective threshold (course threshold + exemption margin
         if an exemption is active).
      3. If rate >= effective threshold AND student is currently eligible →
         block the student, send notifications, and write a CRITIQUE audit log.
      4. If rate < effective threshold AND student is currently blocked →
         restore eligibility and notify the student by email.

    All database writes are wrapped in ``transaction.atomic()`` to ensure
    the eligibility flag and the notification are either both saved or neither.
    Emails are sent via ``transaction.on_commit`` so that an SMTP failure
    cannot roll back the database transaction.

    Args:
        inscription: ``apps.enrollments.models.Inscription`` instance to
            re-evaluate.  The related ``id_cours`` must be accessible.

    Side effects:
      - May update ``inscription.eligible_examen`` and save it.
      - May create a ``Notification`` for the student.
      - May create a ``LogAudit`` entry at CRITIQUE level.
      - May send emails to the student and/or the course professor.
    """
    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]
    total_periodes = stats["total_periodes"]
    cours = inscription.id_cours

    # No sessions scheduled yet → student cannot be blocked; ensure flag is True.
    if total_periodes == 0:
        if not inscription.eligible_examen:
            inscription.eligible_examen = True
            inscription.save(update_fields=["eligible_examen"])
        return

    seuil = cours.get_seuil_absence()
    # Exempted students get extra margin before being blocked.
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil
    doit_bloquer = taux >= seuil_effectif

    if doit_bloquer:
        # Only act when the student was previously eligible (avoid duplicate notifications).
        if inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = False
                inscription.save(update_fields=["eligible_examen"])

                # Build notification message — distinguish exempted vs non-exempted students.
                msg = (
                    f"ALERTE : Seuil d'exemption de {seuil_effectif}% dépassé pour {cours.nom_cours}. "
                    f"Examen bloqué malgré l'exemption."
                    if inscription.exemption_40
                    else f"ALERTE : Seuil de {seuil}% dépassé pour {cours.nom_cours}. Examen bloqué."
                )
                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=msg,
                        type="ALERTE",
                    )
                except Exception:
                    logger.exception("Failed to create blocking notification for %s", cours.nom_cours)

                # Capture references now; closures in on_commit capture by reference
                # and the loop variable would be stale by the time the callback fires.
                student = inscription.id_etudiant
                professor = cours.professeur
                course_name = cours.nom_cours
                transaction.on_commit(
                    lambda: _send_threshold_emails(student, professor, course_name, taux, seuil_effectif)
                )

                # Write a CRITIQUE audit entry so administrators can trace every blocking event.
                try:
                    LogAudit.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        action=(
                            f"CRITIQUE: Blocage automatique examen - {cours.nom_cours} "
                            f"(Taux: {taux:.1f}%, Seuil effectif: {seuil_effectif}%"
                            f"{', exempté' if inscription.exemption_40 else ''})"
                        ),
                        adresse_ip="0.0.0.0",  # nosec B104 — system-generated event, no real IP
                        niveau="CRITIQUE",
                        objet_type="INSCRIPTION",
                        objet_id=inscription.id_inscription,
                    )
                except Exception:
                    logger.exception("Failed to create audit log for blocking %s", cours.nom_cours)
    else:
        # Absence rate is below threshold — restore eligibility if student was blocked.
        if not inscription.eligible_examen:
            with transaction.atomic():
                inscription.eligible_examen = True
                inscription.save(update_fields=["eligible_examen"])

                try:
                    Notification.objects.create(
                        id_utilisateur=inscription.id_etudiant,
                        message=f"Information : Vous êtes à nouveau éligible à l'examen pour {cours.nom_cours}.",
                        type="INFO",
                    )
                except Exception:
                    logger.exception("Failed to create unblocking notification for %s", cours.nom_cours)

                student = inscription.id_etudiant
                course_name = cours.nom_cours

                def _send_restored():
                    """Send the eligibility-restored email after the transaction commits."""
                    subj, body, html_body = build_eligibility_restored_email(student, course_name)
                    send_notification_email(student, subj, body, html_body)

                transaction.on_commit(_send_restored)


def _send_threshold_emails(student, professor, course_name, taux, seuil):
    """
    Send threshold-exceeded notification emails to the student and the professor.

    This function is called via ``transaction.on_commit`` so that SMTP failures
    do not roll back the eligibility change in the database.

    Args:
        student: ``User`` instance for the blocked student.
        professor: ``User`` instance for the course professor, or None.
        course_name (str): human-readable course name for email content.
        taux (float): current absence rate percentage.
        seuil (float): effective threshold that was exceeded.

    Side effects:
        Sends up to two emails (student + professor).  Exceptions are caught
        and logged so that a failing email does not surface as an HTTP 500.
    """
    try:
        subj, body, html_body = build_threshold_exceeded_email(student, course_name, taux, seuil)
        send_notification_email(student, subj, body, html_body)
        if professor:
            subj, body, html_body = build_threshold_exceeded_professor_email(
                professor, student, course_name, taux, seuil
            )
            send_notification_email(professor, subj, body, html_body)
    except Exception:
        logger.exception("Failed to send threshold emails for %s", course_name)


def calculer_risque_inscription(inscription, system_threshold=None):
    """
    Return the complete risk profile for a single enrolment.

    This function is the single source of truth for risk status used by all
    views and APIs.  It consolidates the logic that was previously duplicated
    across 8+ view functions.

    Args:
        inscription: ``apps.enrollments.models.Inscription`` instance.
        system_threshold (int | float | None): pre-loaded system default threshold.
            If None, it is fetched via ``get_system_threshold()``.

    Returns:
        dict with the following keys:

        - ``is_at_risk`` (bool): True if the rate meets the base course threshold.
        - ``is_blocked`` (bool): True if the rate meets the effective threshold
          (after applying any exemption margin).
        - ``is_under_exemption`` (bool): True if the student is at risk but not yet
          blocked because an exemption margin is protecting them.
        - ``taux`` (float): current absence rate, rounded to 1 decimal place.
        - ``seuil`` (int | float): base course threshold.
        - ``seuil_effectif`` (int | float): effective threshold after exemption.
        - ``total_absence`` (float): total unjustified absence hours.
        - ``total_periodes`` (int): total planned course hours.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    cours = inscription.id_cours
    # Use the course-specific threshold when set; fall back to the system default.
    seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
    seuil_effectif = min(seuil + inscription.exemption_margin, 100) if inscription.exemption_40 else seuil

    stats = calculer_absence_stats(inscription)
    taux = stats["taux"]

    is_at_risk = taux >= seuil
    is_blocked = taux >= seuil_effectif
    # Under exemption: student has crossed the base threshold but is still protected
    # by the exemption margin — they should be warned but are not blocked yet.
    is_under_exemption = inscription.exemption_40 and is_at_risk and not is_blocked

    return {
        "is_at_risk": is_at_risk,
        "is_blocked": is_blocked,
        "is_under_exemption": is_under_exemption,
        "taux": round(taux, 1),
        "seuil": seuil,
        "seuil_effectif": seuil_effectif,
        "total_absence": stats["total_absence"],
        "total_periodes": stats["total_periodes"],
    }


def get_at_risk_count_for_queryset(inscriptions_qs, system_threshold=None):
    """
    Count the number of at-risk enrolments in a queryset.

    Optimised for dashboard views: performs a single bulk SQL aggregation
    instead of evaluating each enrolment individually.  This keeps page load
    times acceptable even for large cohorts.

    Args:
        inscriptions_qs: ``QuerySet[Inscription]`` — the set of enrolments to
            examine.  The related ``id_cours`` must be accessible (use
            ``select_related("id_cours")`` before passing).
        system_threshold (int | float | None): pre-loaded system default threshold.
            Reuse a cached value here when calling from a loop to avoid a DB hit
            per enrolment.

    Returns:
        tuple:
          - ``at_risk_count`` (int): number of enrolments whose effective absence
            rate meets or exceeds the effective threshold.
          - ``absence_sums`` (dict): mapping of ``{id_inscription: total_hours}``
            for all enrolments with recorded unjustified absences today.  Callers
            may reuse this dict to avoid duplicate queries.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    inscription_ids = list(inscriptions_qs.values_list("id_inscription", flat=True))
    if not inscription_ids:
        return 0, {}

    today = timezone.localdate()

    # Single aggregation query: sum unjustified absence hours per enrolment.
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    at_risk_count = 0
    for ins in inscriptions_qs:
        cours = ins.id_cours
        # Skip enrolments with no planned hours — they cannot be at risk.
        if not cours.nombre_total_periodes:
            continue
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        total_abs = absence_sums.get(ins.id_inscription, 0) or 0
        taux = min((total_abs / cours.nombre_total_periodes) * 100, 100)
        # Apply exemption margin before comparing against threshold.
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil
        if taux >= seuil_effectif:
            at_risk_count += 1

    return at_risk_count, absence_sums
