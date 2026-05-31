"""
Hub des vues du tableau de bord étudiant pour le système UniAbsences.

Hub de réexportation qui agrège tous les symboles de vues du tableau de bord
étudiant depuis les sous-modules afin que ``dashboard/urls.py`` importe
depuis un espace de noms stable unique.

Structure des sous-modules :
  views_student_dashboard.py  — Tableau de bord KPIs + statut académique
  views_student_statistics.py — Graphiques et statistiques détaillées
  views_student_courses.py    — Liste des cours + détail cours (séances & absences)
  views_student_absences.py   — Liste absences + page rapports PDF
"""

# Réexporte toutes les vues étudiant pour la compatibilité ascendante avec views.py et urls.py.
# Le nouveau code doit importer directement depuis le sous-module spécifique.

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
