"""
Package de services pour la gestion des absences.

Organisation par responsabilité :
  - justification_service.py : délais et validation des justificatifs
  - absence_service.py       : calcul de statistiques et requêtes optimisées
  - eligibility_service.py   : éligibilité examen et calcul de risque centralisé
  - prediction_service.py    : détection prédictive des absences à risque

Toutes les fonctions restent importables depuis apps.absences.services
pour assurer la compatibilité ascendante.
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
