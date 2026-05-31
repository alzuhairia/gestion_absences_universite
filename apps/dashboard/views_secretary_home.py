"""
Concentrateur des vues d'accueil secrétaire pour le tableau de bord UniAbsences.

Concentrateur de réexport pour le tableau de bord principal et les vues de statistiques du secrétariat.

Sous-modules :
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
