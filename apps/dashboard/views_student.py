"""
FICHIER : apps/dashboard/views_student.py
RESPONSABILITE : Re-export centralisé de toutes les vues du dashboard étudiant.

Structure des sous-modules étudiant :
  views_student_dashboard.py  — Dashboard KPIs + statut académique
  views_student_statistics.py — Graphiques et statistiques détaillées
  views_student_courses.py    — Liste des cours + détail cours (séances & absences)
  views_student_absences.py   — Liste absences + page rapports PDF
"""

# Re-export all student views for backward compatibility with views.py and urls.py.
# New code should import directly from the specific sub-module.

from apps.dashboard.views_student_dashboard import (  # noqa: F401
    student_dashboard,
)

from apps.dashboard.views_student_statistics import (  # noqa: F401
    student_statistics,
)

from apps.dashboard.views_student_courses import (  # noqa: F401
    student_course_detail,
    student_courses,
)

from apps.dashboard.views_student_absences import (  # noqa: F401
    student_absences,
    student_reports,
)
