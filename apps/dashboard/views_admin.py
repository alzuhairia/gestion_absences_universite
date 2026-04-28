"""
FICHIER : apps/dashboard/views_admin.py
RESPONSABILITE : Re-export centralisé de toutes les vues admin.

Structure des sous-modules admin :
  views_admin_dashboard.py      — Dashboard principal (KPIs, at-risk cache)
  views_admin_stats.py          — Statistiques avancées (graphiques, top N)
  views_admin_courses.py        — CRUD cours
  views_admin_faculties.py      — CRUD facultés
  views_admin_departments.py    — CRUD départements
  views_admin_academic_years.py — CRUD années académiques
  views_admin_prerequisites.py  — API prérequis par niveau (AJAX)
  views_admin_users.py          — Gestion utilisateurs (CRUD, reset mdp, 2FA)
  views_admin_settings.py       — Paramètres système, audit logs, QR scan logs
"""

# Re-export all admin views so urls.py can do `from . import views_admin`.
# New code should import directly from the specific sub-module.

from apps.dashboard.views_admin_dashboard import (  # noqa: F401
    admin_dashboard_main,
    is_admin,
)
from apps.dashboard.views_admin_stats import admin_statistics  # noqa: F401

from apps.dashboard.views_admin_faculties import (  # noqa: F401
    admin_faculties,
    admin_faculty_edit,
    admin_faculty_delete,
)

from apps.dashboard.views_admin_departments import (  # noqa: F401
    admin_departments,
    admin_department_edit,
    admin_department_delete,
)

from apps.dashboard.views_admin_courses import (  # noqa: F401
    admin_courses,
    admin_course_edit,
    admin_course_delete,
    admin_courses_delete_multiple,
)

from apps.dashboard.views_admin_academic_years import (  # noqa: F401
    admin_academic_years,
    admin_academic_year_set_active,
    admin_academic_year_delete,
)

from apps.dashboard.views_admin_prerequisites import (  # noqa: F401
    get_prerequisites_by_level,
)

from apps.dashboard.views_admin_users import (  # noqa: F401
    admin_user_audit,
    admin_user_create,
    admin_user_delete,
    admin_user_edit,
    admin_user_reset_2fa,
    admin_user_reset_password,
    admin_users,
    admin_users_delete_multiple,
)

from apps.dashboard.views_admin_settings import (  # noqa: F401
    admin_audit_logs,
    admin_export_audit_csv,
    admin_qr_scan_logs,
    admin_settings,
)
