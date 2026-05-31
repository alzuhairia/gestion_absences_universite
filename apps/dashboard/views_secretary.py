"""
Concentrateur des vues du tableau de bord secrétaire pour le système UniAbsences.

Ce module est un concentrateur de réexport qui agrège tous les symboles de vue CRUD et
d'audit destinés au secrétaire depuis les sous-modules dédiés dans un seul espace de noms stable
afin que ``dashboard/urls.py`` puisse importer depuis un emplacement unique. Aucune logique n'est
implémentée ici ; voir les sous-modules individuels pour la documentation complète.

Responsabilités des sous-modules
--------------------------------
``views_secretary_faculties.py``
    ``secretary_faculties``       — liste et création de facultés.
    ``secretary_faculty_edit``    — modifie ou désactive une faculté.
    ``secretary_faculty_delete``  — supprime une faculté avec cascade complet
                                    (départements → cours → inscriptions →
                                    absences → justifications).

``views_secretary_departments.py``
    ``secretary_departments``       — liste et création de départements.
    ``secretary_department_edit``   — modifie ou désactive un département.
    ``secretary_department_delete`` — supprime avec cascade (cours et descendants).

``views_secretary_courses.py``
    ``secretary_courses``                — liste et création de cours.
    ``secretary_course_edit``            — modifie ou désactive un cours.
    ``secretary_course_delete``          — supprime un cours unique avec cascade.
    ``secretary_courses_delete_multiple``— suppression en masse avec cascade.

``views_secretary_academic_years.py``
    ``secretary_academic_years``            — liste et création d'années académiques.
    ``secretary_academic_year_set_active``  — désigne une année comme active
                                             (désactive atomiquement toutes les autres).
    ``secretary_academic_year_delete``      — supprime une année non active avec
                                             cascade ; bloqué sur l'année active.

``views_secretary_audit.py``
    ``secretary_audit_logs`` — vue paginée et filtrée de toutes les entrées du journal d'audit.

Fait partie du tableau de bord UniAbsences.
"""

# Réexporter toutes les vues secrétaire afin que urls.py puisse faire `from . import views_secretary`.
# Le nouveau code doit importer directement depuis le sous-module spécifique.

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
