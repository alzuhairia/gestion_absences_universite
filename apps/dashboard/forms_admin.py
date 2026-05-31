"""
Hub de formulaires d'administration pour le tableau de bord UniAbsences.

Hub de réexportation qui agrège tous les symboles de formulaires
d'administration des trois sous-modules en un seul espace de noms
stable pour les vues et les templates.

Sub-modules
-----------
``forms_admin_academic.py``  — ``FaculteForm``, ``DepartementForm``, ``CoursForm``.
``forms_admin_users.py``     — ``UserForm``.
``forms_admin_settings.py``  — ``SystemSettingsForm``, ``AnneeAcademiqueForm``.

Fait partie du système de tableau de bord UniAbsences.
"""

from apps.dashboard.forms_admin_academic import (  # noqa: F401
    CoursForm,
    DepartementForm,
    FaculteForm,
)
from apps.dashboard.forms_admin_settings import (  # noqa: F401
    AnneeAcademiqueForm,
    SystemSettingsForm,
)
from apps.dashboard.forms_admin_users import UserForm  # noqa: F401
