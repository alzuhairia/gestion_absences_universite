"""
Predictive Risk-Detection Service — apps/absences/services/prediction_service.py

Part of the UniAbsences university attendance management system.

This module projects a student's end-of-semester absence rate using linear
extrapolation from current absence data and classifies the result into one
of four risk levels (HIGH / MEDIUM / LOW / NONE).

Algorithm
---------
1. Compute the current absence rate from past sessions (NON_JUSTIFIEE only).
2. Compute the recent trend rate from the last 30 days.
3. Extrapolate to semester end via linear interpolation using the ratio
   of elapsed / total session hours.
4. Compare the projected rate against 75 % and 50 % of the effective
   threshold (course threshold + exemption margin if applicable) to assign
   HIGH, MEDIUM, LOW, or NONE risk.
"""
import datetime
import logging
from collections import defaultdict

from django.db.models import Sum
from django.utils import timezone

from ..models import Absence
from .eligibility_service import get_system_threshold

logger = logging.getLogger(__name__)

# Predictive risk level constants — returned in each result dict.
# Callers should compare against these constants, not raw strings.
RISK_HIGH = "HIGH"
RISK_MEDIUM = "MEDIUM"
RISK_LOW = "LOW"
RISK_NONE = "NONE"


def predict_absence_risk(inscriptions, academic_year=None, system_threshold=None):
    """
    Perform predictive risk detection for a collection of enrolments.

    For each enrolment this function:
      1. Computes the student's current unjustified absence rate.
      2. Computes a 30-day recent rate and a previous 30-day rate to determine
         the absence trend (up / stable / down).
      3. Linearly extrapolates the projected rate to the end of the semester
         by multiplying the recent daily absence pace by the days remaining.
      4. Classifies the enrolment into one of four risk levels by comparing
         both the current and projected rates against fractions of the
         effective threshold (75 % and 50 % trigger MEDIUM / LOW respectively).

    All absence queries are batched into three aggregation queries upfront
    (total, recent 30 days, previous 30 days) to avoid N+1 patterns.

    Args:
        inscriptions (list[Inscription]): enrolments to evaluate.  The
            related ``id_cours`` field must already be loaded.
        academic_year (AnneeAcademique | None): academic year instance used to
            determine the semester date range (first and last session dates).
            When None, ``days_remaining`` is set to 0 and the projected rate
            equals the current rate.
        system_threshold (int | float | None): pre-loaded system-wide default
            absence threshold.  If None, it is fetched via
            ``get_system_threshold()``.

    Returns:
        list[dict]: one dict per enrolment, ordered to match the input list.
        Each dict contains:

        - ``inscription``: the ``Inscription`` instance.
        - ``risk_level`` (str): one of ``RISK_HIGH``, ``RISK_MEDIUM``,
          ``RISK_LOW``, or ``RISK_NONE``.
        - ``current_rate`` (float): current unjustified absence rate (0-100).
        - ``recent_rate`` (float): absence rate accumulated in the last 30 days.
        - ``projected_rate`` (float): linearly extrapolated end-of-semester rate.
        - ``course_avg_rate`` (float): mean absence rate across all enrolled
          students in the same course (used as a peer benchmark).
        - ``seuil`` (int | float): base course threshold (before exemption).
        - ``total_abs`` (float): total unjustified absence hours to date.
        - ``recent_abs`` (float): unjustified absence hours in the last 30 days.
        - ``days_remaining`` (int): calendar days until the last session.
        - ``trend`` (str): ``"up"``, ``"down"``, or ``"stable"`` based on the
          change in absence hours between the previous and current 30-day window.
    """
    if system_threshold is None:
        system_threshold = get_system_threshold()

    if not inscriptions:
        return []

    today = timezone.localdate()
    thirty_days_ago = today - datetime.timedelta(days=30)
    sixty_days_ago = today - datetime.timedelta(days=60)

    inscription_ids = [ins.id_inscription for ins in inscriptions]
    # Use a list so the filter uses __in rather than exact match.
    _non_justified = [Absence.Statut.NON_JUSTIFIEE]

    # --- Batch query 1: total unjustified absence hours up to today ---
    total_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # --- Batch query 2: recent window (last 30 days) absence hours ---
    recent_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__gte=thirty_days_ago,
            id_seance__date_seance__lte=today,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # --- Batch query 3: previous window (30-60 days ago) for trend calculation ---
    prev_abs_map = dict(
        Absence.objects.filter(
            id_inscription__in=inscription_ids,
            statut__in=_non_justified,
            id_seance__date_seance__gte=sixty_days_ago,
            id_seance__date_seance__lt=thirty_days_ago,
        )
        .values("id_inscription")
        .annotate(total=Sum("duree_absence"))
        .values_list("id_inscription", "total")
    )

    # Compute the mean absence rate per course to use as a peer benchmark.
    # Students whose recent rate significantly exceeds the course average are
    # flagged as MEDIUM risk even if their projected rate is below 75 % of threshold.
    course_inscriptions = defaultdict(list)
    for ins in inscriptions:
        course_inscriptions[ins.id_cours_id].append(ins)

    course_avg_map = {}
    for course_id, course_ins_list in course_inscriptions.items():
        cours = course_ins_list[0].id_cours
        if not cours.nombre_total_periodes:
            course_avg_map[course_id] = 0.0
            continue
        rates = [
            min((float(total_abs_map.get(ins.id_inscription, 0) or 0) / cours.nombre_total_periodes) * 100, 100)
            for ins in course_ins_list
        ]
        course_avg_map[course_id] = sum(rates) / len(rates) if rates else 0.0

    # Determine the semester time bounds from actual session records.
    from apps.academic_sessions.models import Seance
    if academic_year:
        last_session = (
            Seance.objects.filter(id_annee=academic_year)
            .order_by("-date_seance")
            .values_list("date_seance", flat=True)
            .first()
        )
        first_session = (
            Seance.objects.filter(id_annee=academic_year)
            .order_by("date_seance")
            .values_list("date_seance", flat=True)
            .first()
        )
        # days_remaining is 0 when the last session is today or in the past.
        days_remaining = (last_session - today).days if last_session and last_session > today else 0
    else:
        # No academic year provided — projection is disabled.
        last_session = first_session = None
        days_remaining = 0

    results = []
    for ins in inscriptions:
        cours = ins.id_cours
        total_periodes = cours.nombre_total_periodes or 0

        # No planned hours — risk cannot be computed; emit a safe NONE result.
        if total_periodes == 0:
            results.append({
                "inscription": ins,
                "risk_level": RISK_NONE,
                "current_rate": 0.0,
                "recent_rate": 0.0,
                "projected_rate": 0.0,
                "course_avg_rate": 0.0,
                "seuil": system_threshold,
                "total_abs": 0.0,
                "recent_abs": 0.0,
                "days_remaining": days_remaining,
            })
            continue

        # Effective threshold: add the exemption margin for exempted students.
        seuil = cours.seuil_absence if cours.seuil_absence is not None else system_threshold
        seuil_effectif = min(seuil + ins.exemption_margin, 100) if ins.exemption_40 else seuil

        total_abs = float(total_abs_map.get(ins.id_inscription, 0) or 0)
        recent_abs = float(recent_abs_map.get(ins.id_inscription, 0) or 0)
        prev_abs = float(prev_abs_map.get(ins.id_inscription, 0) or 0)
        course_avg = course_avg_map.get(ins.id_cours_id, 0.0)

        current_rate = min((total_abs / total_periodes) * 100, 100)

        # Compute how many days have elapsed since the first session to normalise
        # the recent window size (avoids artificially high rates at semester start).
        window_days = min(30, max((today - first_session).days, 1)) if first_session else 30
        recent_daily_rate = recent_abs / window_days if window_days > 0 else 0

        # Linear extrapolation: project absence hours to semester end.
        projected_hours = total_abs + (recent_daily_rate * days_remaining)
        projected_rate = (projected_hours / total_periodes) * 100 if days_remaining > 0 else current_rate
        recent_rate = min((recent_abs / total_periodes) * 100, 100)

        # Trend: compare recent 30-day window against the previous 30-day window.
        # A > 10 % relative increase is flagged as "up"; > 10 % decrease as "down".
        if prev_abs > 0:
            change_ratio = (recent_abs - prev_abs) / prev_abs
            trend = "up" if change_ratio > 0.10 else ("down" if change_ratio < -0.10 else "stable")
        elif recent_abs > 0:
            # No previous window data but absences are accumulating — trend is up.
            trend = "up"
        else:
            trend = "stable"

        # --- Risk classification ---
        # HIGH:   already at or above threshold, OR projected to exceed threshold,
        #         OR currently at 75 % of threshold (imminent breach).
        # MEDIUM: projected to reach 75 % of threshold, OR recent rate is more
        #         than double the course average (outlier behaviour).
        # LOW:    projected to reach 50 % of threshold AND rate exceeds course avg.
        # NONE:   none of the above conditions are met.
        if current_rate >= seuil_effectif:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil_effectif or current_rate >= seuil_effectif * 0.75:
            risk_level = RISK_HIGH
        elif projected_rate >= seuil_effectif * 0.75 or (course_avg > 0 and recent_rate > course_avg * 2):
            risk_level = RISK_MEDIUM
        elif projected_rate >= seuil_effectif * 0.50 and (course_avg > 0 and recent_rate > course_avg):
            risk_level = RISK_LOW
        else:
            risk_level = RISK_NONE

        results.append({
            "inscription": ins,
            "risk_level": risk_level,
            "current_rate": round(current_rate, 1),
            "recent_rate": round(recent_rate, 1),
            "projected_rate": round(min(projected_rate, 100.0), 1),
            "course_avg_rate": round(course_avg, 1),
            "seuil": seuil,
            "total_abs": total_abs,
            "recent_abs": recent_abs,
            "days_remaining": days_remaining,
            "trend": trend,
        })

    return results
