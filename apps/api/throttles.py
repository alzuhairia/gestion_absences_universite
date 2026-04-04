"""
Throttles scopes pour l'API REST.
Limite les operations d'ecriture sensibles independamment du throttle global.
"""

from rest_framework.throttling import UserRateThrottle


class AbsenceWriteThrottle(UserRateThrottle):
    """Limite la creation/modification d'absences a 60/heure par utilisateur."""

    scope = "absence_write"


class JustificationUploadThrottle(UserRateThrottle):
    """Limite la soumission de justificatifs a 20/heure par utilisateur."""

    scope = "justification_upload"
