"""
Justification Deadline Service — apps/absences/services/justification_service.py

Part of the UniAbsences university attendance management system.

Single responsibility: calculate and check the submission deadline for a
student's absence justification document.

Business rule:
    A student has ``JUSTIFICATION_DEADLINE_DAYS`` calendar days after the
    session date to submit a supporting document.  After this deadline the
    submission window is closed and the absence can no longer be justified.
    The deadline is inclusive — a student may submit on the last day itself.
"""
import datetime

from django.utils import timezone

# Number of calendar days after the session date during which the student
# may submit a justification document.  After this window the absence is
# permanently treated as unjustified.
JUSTIFICATION_DEADLINE_DAYS = 3


def get_justification_deadline(absence):
    """
    Return the last date on which the student may submit a justification
    document for a given absence.

    The deadline is calculated as:
        deadline = session_date + JUSTIFICATION_DEADLINE_DAYS

    Args:
        absence: ``apps.absences.models.Absence`` instance whose related
            ``id_seance`` must be accessible (provides ``date_seance``).

    Returns:
        datetime.date: the inclusive deadline date for document submission.
    """
    return absence.id_seance.date_seance + datetime.timedelta(
        days=JUSTIFICATION_DEADLINE_DAYS
    )


def is_justification_expired(absence):
    """
    Return whether the justification submission window has closed for an absence.

    The deadline day is inclusive: a student who submits on the deadline date
    itself is still within the allowed window.

    Args:
        absence: ``apps.absences.models.Absence`` instance whose related
            ``id_seance`` must be accessible.

    Returns:
        bool: True if today is strictly after the deadline date (window closed),
        False if the student may still submit a justification document.
    """
    deadline = get_justification_deadline(absence)
    today = timezone.localdate()
    # Strict comparison: today > deadline means the window is closed.
    return today > deadline
