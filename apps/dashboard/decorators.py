"""
Hub des décorateurs du dashboard pour le système UniAbsences.

Hub de ré-exports qui agrège tous les symboles de décorateurs des deux
sous-modules afin que les vues et les URLs puissent les importer depuis
un seul espace de noms stable.

Sous-modules
------------
``decorators_roles.py`` — ``admin_required``, ``secretary_required``,
                          ``professor_required``, ``roles_required``,
                          ``student_required``.
``decorators_api.py``   — ``api_ok``, ``api_error``, ``new_request_id``,
                          ``api_login_required``.

Partie du système dashboard UniAbsences.
"""

from apps.dashboard.decorators_api import (  # noqa: F401
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
)
from apps.dashboard.decorators_roles import (  # noqa: F401
    admin_required,
    professor_required,
    roles_required,
    secretary_required,
    student_required,
)
