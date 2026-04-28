"""
FICHIER : apps/dashboard/views_secretary.py
RESPONSABILITE : Re-export centralisé de toutes les vues secrétaire.

Structure des sous-modules secrétaire :
  views_secretary_faculties.py       — CRUD facultés
  views_secretary_departments.py     — CRUD départements
  views_secretary_courses.py         — CRUD cours
  views_secretary_academic_years.py  — CRUD années académiques
  views_secretary_audit.py           — Journaux d'audit
"""

# Re-export all secretary views so urls.py can do `from . import views_secretary`.
# New code should import directly from the specific sub-module.

from apps.dashboard.views_secretary_faculties import (  # noqa: F401
    secretary_faculties,
    secretary_faculty_edit,
    secretary_faculty_delete,
)

from apps.dashboard.views_secretary_departments import (  # noqa: F401
    secretary_departments,
    secretary_department_edit,
    secretary_department_delete,
)

from apps.dashboard.views_secretary_courses import (  # noqa: F401
    secretary_courses,
    secretary_course_edit,
    secretary_course_delete,
    secretary_courses_delete_multiple,
)

from apps.dashboard.views_secretary_academic_years import (  # noqa: F401
    secretary_academic_years,
    secretary_academic_year_set_active,
    secretary_academic_year_delete,
)

from apps.dashboard.views_secretary_audit import (  # noqa: F401
    secretary_audit_logs,
)
