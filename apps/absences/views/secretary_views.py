"""
Hub de ré-export des vues du secrétariat — apps/absences/views/secretary_views.py

Centralise toutes les vues orientées secrétariat du module d'absences afin
qu'``absences/urls.py`` puisse les importer depuis un unique espace de
noms stable.

Sous-modules
------------
``secretary_justification.py``    — ``review_justification``, ``validation_list``,
                                    ``process_justification``, ``justified_absences_list``.
``secretary_absence_encoding.py`` — ``create_justified_absence``,
                                    ``secretary_student_history_api``.
``secretary_absence_edit.py``     — ``edit_absence``.

Fait partie du système d'absences UniAbsences.
"""

from .secretary_justification import (  # noqa: F401
    justified_absences_list,
    process_justification,
    review_justification,
    validation_list,
)
from .secretary_absence_encoding import (  # noqa: F401
    create_justified_absence,
    secretary_student_history_api,
)
from .secretary_absence_edit import edit_absence  # noqa: F401
