"""
FICHIER : apps/dashboard/views_professor.py
RESPONSABILITE : Re-export centralisé de toutes les vues du dashboard professeur.

Structure des sous-modules professeur :
  views_professor_dashboard.py      — Dashboard KPIs + étudiants à risque
  views_professor_course_detail.py  — Détail d'un cours (étudiants, séances, stats)
  views_professor_course_list.py    — Liste des cours assignés
  views_professor_sessions.py       — Liste des séances + statistiques globales
"""

# Re-export all professor views for backward compatibility with views.py and urls.py.
# New code should import directly from the specific sub-module.

from apps.dashboard.views_professor_dashboard import (  # noqa: F401
    instructor_dashboard,
)

from apps.dashboard.views_professor_course_detail import (  # noqa: F401
    instructor_course_detail,
)

from apps.dashboard.views_professor_course_list import (  # noqa: F401
    instructor_courses,
)

from apps.dashboard.views_professor_sessions import (  # noqa: F401
    instructor_sessions,
    instructor_statistics,
)
