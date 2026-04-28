"""
FICHIER : apps/absences/views/secretary_views.py
RESPONSABILITE : Re-export centralisé des vues secrétariat pour les absences.

Organisation :
  secretary_justification.py    — review_justification, validation_list,
                                   process_justification, justified_absences_list
  secretary_absence_encoding.py — create_justified_absence, student_absence_history_api
"""

from .secretary_justification import (  # noqa: F401
    justified_absences_list,
    process_justification,
    review_justification,
    validation_list,
)
from .secretary_absence_encoding import (  # noqa: F401
    create_justified_absence,
    student_absence_history_api,
)
