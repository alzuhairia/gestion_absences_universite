"""
FICHIER : apps/dashboard/views_secretary_home.py
RESPONSABILITE : Re-export hub — vues principales du secrétariat

Organisation :
  views_secretary_main.py  — dashboard, get_active_courses_queryset, active_courses
  views_secretary_stats.py — inscriptions, seuils d'absence, exports
"""

from apps.dashboard.views_secretary_main import (  # noqa: F401
    get_active_courses_queryset,
    secretary_dashboard,
    active_courses,
)
from apps.dashboard.views_secretary_stats import (  # noqa: F401
    secretary_enrollments,
    secretary_seuils_absence,
    secretary_exports,
)
