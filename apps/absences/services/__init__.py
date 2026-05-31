"""
Absence Services Package — apps/absences/services/__init__.py

Part of the UniAbsences university attendance management system.

This package is the central business-logic layer for the absences application.
It is split into four single-responsibility modules, each covering a distinct
aspect of the absence-management domain:

  - ``justification_service.py`` : deadline calculation and expiry checks for
    student-submitted justification documents.
  - ``absence_service.py``       : core statistics computation (absence hours,
    percentages, and alert detection) with optimised querysets.
  - ``eligibility_service.py``   : exam eligibility decisions and bulk risk
    counting — the authoritative source of truth for blocking logic.
  - ``prediction_service.py``    : linear-extrapolation risk forecasting that
    warns before a student actually reaches the threshold.

All public symbols are re-exported from this package so that callers can use
``from apps.absences.services import <name>`` regardless of which sub-module
the symbol lives in, preserving backwards compatibility.
"""
from .justification_service import (
    JUSTIFICATION_DEADLINE_DAYS,
    get_justification_deadline,
    is_justification_expired,
)
from .absence_service import (
    calculer_absence_stats,
    get_absences_queryset,
    calculer_pourcentage_absence,
    etudiants_en_alerte,
)
from .eligibility_service import (
    recalculer_eligibilite,
    get_system_threshold,
    calculer_risque_inscription,
    get_at_risk_count_for_queryset,
)
from .prediction_service import (
    predict_absence_risk,
    RISK_HIGH,
    RISK_MEDIUM,
    RISK_LOW,
    RISK_NONE,
)

__all__ = [
    "JUSTIFICATION_DEADLINE_DAYS",
    "get_justification_deadline",
    "is_justification_expired",
    "calculer_absence_stats",
    "get_absences_queryset",
    "calculer_pourcentage_absence",
    "etudiants_en_alerte",
    "recalculer_eligibilite",
    "get_system_threshold",
    "calculer_risque_inscription",
    "get_at_risk_count_for_queryset",
    "predict_absence_risk",
    "RISK_HIGH",
    "RISK_MEDIUM",
    "RISK_LOW",
    "RISK_NONE",
]
