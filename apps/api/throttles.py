"""
Classes de throttle pour les opérations sensibles aux écritures dans l'API REST UniAbsences.

Les paramètres globaux de throttle de DRF (définis dans ``settings/base.py``
sous ``DEFAULT_THROTTLE_RATES``) s'appliquent uniformément à tous les endpoints.
Ce module définit des *scopes nommés* qui permettent à des endpoints de modification
spécifiques d'appliquer des limites de débit indépendantes plus strictes sans
affecter les opérations de lecture ou d'autres endpoints d'écriture.

Chaque classe correspond à un nom de scope qui doit avoir une entrée correspondante
dans le dictionnaire ``REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` des paramètres Django,
par exemple ::

    REST_FRAMEWORK = {
        "DEFAULT_THROTTLE_RATES": {
            "absence_write": "60/hour",
            "justification_upload": "20/hour",
        }
    }

Responsabilités :
  - AbsenceWriteThrottle      : limiter les appels de création/mise à jour
                                d'absence par utilisateur et par heure pour empêcher
                                les abus d'enregistrement en masse.
  - JustificationUploadThrottle: limiter les appels de soumission de justification
                                par utilisateur et par heure pour empêcher le spam
                                de dépôt de documents.

Fait partie de l'API REST UniAbsences.
"""

from rest_framework.throttling import UserRateThrottle


class AbsenceWriteThrottle(UserRateThrottle):
    """
    Limite le débit des opérations de création et de mise à jour d'absences.

    Appliqué par ``AbsenceViewSet.get_throttles()`` pour les actions ``create``,
    ``update`` et ``partial_update``. La limite réelle est lue depuis
    ``DEFAULT_THROTTLE_RATES["absence_write"]`` dans les paramètres Django
    (par défaut : 60 requêtes par heure par utilisateur authentifié).

    L'utilisation d'un throttle par utilisateur (``UserRateThrottle``) signifie que
    la limite est suivie indépendamment pour chaque utilisateur connecté, empêchant
    un professeur ou un secrétaire d'inonder accidentellement ou malicieusement
    l'endpoint d'enregistrement d'absences.
    """

    # Clé de scope — doit correspondre à une entrée dans DEFAULT_THROTTLE_RATES
    scope = "absence_write"


class JustificationUploadThrottle(UserRateThrottle):
    """
    Limite le débit des soumissions de documents de justification.

    Appliqué par ``JustificationViewSet.get_throttles()`` pour l'action ``create``.
    La limite réelle est lue depuis
    ``DEFAULT_THROTTLE_RATES["justification_upload"]`` dans les paramètres Django
    (par défaut : 20 requêtes par heure par utilisateur authentifié).

    Une limite plus basse que ``AbsenceWriteThrottle`` est intentionnelle : on s'attend
    à ce que les étudiants soumettent au plus quelques justifications par session,
    et un taux de soumission très élevé est un signal fort d'abus automatisé.
    """

    # Clé de scope — doit correspondre à une entrée dans DEFAULT_THROTTLE_RATES
    scope = "justification_upload"
