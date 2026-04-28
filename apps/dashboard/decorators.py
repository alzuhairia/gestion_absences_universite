"""
FICHIER : apps/dashboard/decorators.py
RESPONSABILITE : Re-export hub — décorateurs de sécurité et utilitaires API

Sous-modules :
  decorators_roles.py — admin_required, secretary_required, professor_required,
                        roles_required, student_required
  decorators_api.py   — api_ok, api_error, new_request_id, api_login_required
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
