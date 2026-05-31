"""
Secretary absences views hub — apps/absences/views/secretary_views.py

Re-export hub for all secretariat-facing absence views so that
``absences/urls.py`` imports from a single stable namespace.

Sub-modules
-----------
``secretary_justification.py``    — ``review_justification``, ``validation_list``,
                                    ``process_justification``, ``justified_absences_list``.
``secretary_absence_encoding.py`` — ``create_justified_absence``,
                                    ``student_absence_history_api``.

Part of the UniAbsences absences system.
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
