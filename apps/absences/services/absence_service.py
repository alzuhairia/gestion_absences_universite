"""
Absence Statistics Service — apps/absences/services/absence_service.py

Part of the UniAbsences university attendance management system.

This module provides the core calculation layer for absence statistics.
It is the single source of truth for computing absence hours, rates, and
alert detection for a given course enrolment.

Main responsibilities:
  - ``calculer_absence_stats``      : compute raw absence stats for one enrolment
  - ``get_absences_queryset``       : return an N+1-safe queryset for displaying absences
  - ``calculer_pourcentage_absence``: compute real hour-based absence/presence percentages
  - ``etudiants_en_alerte``         : list students whose absence rate exceeds the course threshold

Business rules enforced here:
  - Only NON_JUSTIFIEE absences count against the student.
    EN_ATTENTE (justification submitted but not yet reviewed) does NOT penalise.
  - Only past sessions (date <= today) are counted; future sessions are excluded.
  - Absence rate = total unjustified absence hours / total scheduled course hours.
"""
import logging

from django.db.models import DurationField, ExpressionWrapper, F, Sum
from django.utils import timezone

from ..models import Absence

logger = logging.getLogger(__name__)


def calculer_absence_stats(inscription):
    """
    Compute the absence statistics for a single course enrolment.

    Only NON_JUSTIFIEE absences from past sessions (date <= today) are
    included, so that a pending justification (EN_ATTENTE) does not
    penalise the student before the secretary has reviewed it.

    Args:
        inscription: ``apps.enrollments.models.Inscription`` instance whose
            related ``id_cours`` must already be accessible.

    Returns:
        dict with the following keys:

        - ``total_absence`` (float): total unjustified absence hours.
        - ``taux`` (float): absence rate as a percentage (0–100), capped at 100.
        - ``total_periodes`` (int): total planned course hours (denominator).
    """
    # Only NON_JUSTIFIEE absences for PAST sessions count.
    # EN_ATTENTE = justificatif soumis, should not penalise the student
    # until the secretary makes a decision.
    today = timezone.localdate()
    total_absence = float(
        Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    total_periodes = inscription.id_cours.nombre_total_periodes or 0
    # Cap at 100 % to avoid displaying rates above 100 in edge cases.
    taux = min((total_absence / total_periodes) * 100, 100) if total_periodes else 0

    return {
        "total_absence": total_absence,
        "taux": taux,
        "total_periodes": total_periodes,
    }


def get_absences_queryset(inscription):
    """
    Return an optimised queryset of all absences for a given enrolment.

    Uses ``select_related`` to avoid N+1 queries when accessing session
    and justification data in the template layer.  Results are ordered
    most-recent session first.

    Args:
        inscription: ``apps.enrollments.models.Inscription`` instance.

    Returns:
        ``QuerySet[Absence]``: absence records ordered by ``-id_seance__date_seance``.
    """
    return (
        Absence.objects.filter(id_inscription=inscription)
        .select_related("id_seance", "id_seance__id_cours", "justification")
        .order_by("-id_seance__date_seance")
    )


def calculer_pourcentage_absence(etudiant, cours):
    """
    Compute real hour-based absence and presence percentages for one student
    in a given course.

    Design decisions:
      - No ``Absence`` record means the student was PRESENT (absence-by-exception model).
      - Only NON_JUSTIFIEE absences count (EN_ATTENTE does not penalise).
      - Only past sessions (date <= today) are counted.
      - If the student is not actively enrolled, the presence rate is 100 %.

    Args:
        etudiant: ``apps.accounts.models.User`` instance (student).
        cours: ``apps.academics.models.Cours`` instance.

    Returns:
        dict with the following keys:

        - ``total_heures_cours`` (float): total hours of past sessions.
        - ``total_heures_absence`` (float): total unjustified absence hours.
        - ``pourcentage_absence`` (float): absence rate 0–100, rounded to 2 d.p.
        - ``pourcentage_presence`` (float): presence rate 0–100, rounded to 2 d.p.

        All values are 0.0 / 100.0 when no sessions have taken place yet.
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    today = timezone.localdate()

    # Total course hours = sum of (heure_fin - heure_debut) for all PAST sessions.
    # ExpressionWrapper is required because Django cannot directly sum DurationField
    # values computed from time differences.
    raw = Seance.objects.filter(
        id_cours=cours, date_seance__lte=today
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("heure_fin") - F("heure_debut"),
                output_field=DurationField(),
            )
        )
    )["total"]
    total_heures_cours = round(raw.total_seconds() / 3600.0, 2) if raw else 0.0

    # Guard: no past sessions yet — return all-zero dict.
    if total_heures_cours == 0:
        return {
            "total_heures_cours": 0.0,
            "total_heures_absence": 0.0,
            "pourcentage_absence": 0.0,
            "pourcentage_presence": 0.0,
        }

    inscription = Inscription.objects.filter(
        id_etudiant=etudiant,
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).first()

    # Student is not actively enrolled → treat as 100 % present.
    if not inscription:
        return {
            "total_heures_cours": round(total_heures_cours, 2),
            "total_heures_absence": 0.0,
            "pourcentage_absence": 0.0,
            "pourcentage_presence": 100.0,
        }

    total_heures_absence = float(
        Absence.objects.filter(
            id_inscription=inscription,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        ).aggregate(total=Sum("duree_absence"))["total"]
        or 0
    )

    # Cap absence percentage at 100 % to handle data inconsistencies gracefully.
    pourcentage_absence = min(round((total_heures_absence / total_heures_cours) * 100, 2), 100)
    pourcentage_presence = round(100 - pourcentage_absence, 2)

    return {
        "total_heures_cours": round(total_heures_cours, 2),
        "total_heures_absence": round(total_heures_absence, 2),
        "pourcentage_absence": pourcentage_absence,
        "pourcentage_presence": pourcentage_presence,
    }


def etudiants_en_alerte(cours, seuil=None):
    """
    Return a list of all enrolled students whose absence rate meets or exceeds
    the course threshold.

    The function uses a single bulk aggregation query for all enrolments (rather
    than one query per student) to keep the operation O(1) in database round-trips
    regardless of class size.

    Args:
        cours: ``apps.academics.models.Cours`` instance.
        seuil (int | float | None): absence threshold percentage (0–100).
            Defaults to ``cours.get_seuil_absence()`` if the method exists,
            otherwise falls back to 20 %.

    Returns:
        list[dict]: one dict per at-risk student, sorted by
        ``pourcentage_absence`` descending.  Each dict contains:

        - ``etudiant``: User instance.
        - ``inscription``: Inscription instance.
        - ``pourcentage_absence`` (float): current unjustified absence rate.
        - ``total_heures_absence`` (float): total unjustified absence hours.
        - ``total_heures_cours`` (float): total past session hours for the course.
        - ``depasse_seuil`` (bool): always True (only at-risk students are returned).
    """
    from apps.academic_sessions.models import Seance
    from apps.enrollments.models import Inscription

    if seuil is None:
        # Prefer the course's own threshold method; fall back to a sensible default.
        seuil = cours.get_seuil_absence() if hasattr(cours, "get_seuil_absence") else 20

    today = timezone.localdate()

    # Step 1: compute total hours for past sessions of this course.
    raw = Seance.objects.filter(
        id_cours=cours, date_seance__lte=today
    ).aggregate(
        total=Sum(
            ExpressionWrapper(
                F("heure_fin") - F("heure_debut"),
                output_field=DurationField(),
            )
        )
    )["total"]
    total_heures_cours = round(raw.total_seconds() / 3600.0, 2) if raw else 0.0

    # No sessions have taken place — nobody can be at risk yet.
    if total_heures_cours == 0:
        return []

    # Step 2: fetch all active enrolments for this course.
    inscriptions = Inscription.objects.filter(
        id_cours=cours,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_etudiant")

    # Step 3: bulk-aggregate unjustified absence hours per enrolment.
    # This avoids a per-student query loop (N+1 prevention).
    absence_sums = dict(
        Absence.objects.filter(
            id_inscription__in=inscriptions,
            statut=Absence.Statut.NON_JUSTIFIEE,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Step 4: classify each enrolment as at-risk or not.
    alertes = []
    for ins in inscriptions:
        total_abs = float(absence_sums.get(ins.id_inscription, 0) or 0)
        pourcentage = min(round((total_abs / total_heures_cours) * 100, 2), 100)
        if pourcentage >= seuil:
            alertes.append({
                "etudiant": ins.id_etudiant,
                "inscription": ins,
                "pourcentage_absence": pourcentage,
                "total_heures_absence": round(total_abs, 2),
                "total_heures_cours": round(total_heures_cours, 2),
                "depasse_seuil": True,
            })

    # Return highest-risk students first.
    alertes.sort(key=lambda x: x["pourcentage_absence"], reverse=True)
    return alertes
