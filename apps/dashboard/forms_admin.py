"""
FICHIER : apps/dashboard/forms_admin.py
RESPONSABILITE : Re-export hub — formulaires admin

Sous-modules :
  forms_admin_academic.py  — FaculteForm, DepartementForm, CoursForm
  forms_admin_users.py     — UserForm
  forms_admin_settings.py  — SystemSettingsForm, AnneeAcademiqueForm
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
