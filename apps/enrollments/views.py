"""
FICHIER : apps/enrollments/views.py
RESPONSABILITE : Re-export centralisé des vues d'inscription pour backward compatibility avec urls.py.

Organisation :
  enrollment_handlers.py — get_prerequisite_info, _handle_level_enrollment, _handle_course_enrollment
  enrollment_views.py    — enrollment_manager, enroll_student (imports handlers)
  enrollment_api.py      — get_departments, get_courses, get_courses_by_year, get_courses_by_student
"""

from .enrollment_views import (  # noqa: F401
    enrollment_manager,
    enroll_student,
    get_prerequisite_info,
)
from .enrollment_api import (  # noqa: F401
    get_courses,
    get_courses_by_student,
    get_courses_by_year,
    get_departments,
)
