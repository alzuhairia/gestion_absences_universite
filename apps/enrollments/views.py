"""
Central re-export module for the enrollments application views.

This file exists solely for backward compatibility with ``urls.py``.
As the codebase grew, the enrollment logic was split across three modules
for maintainability:

- ``enrollment_handlers.py`` — business logic for level and course enrollment
- ``enrollment_views.py``    — Django views that drive the enrollment UI
- ``enrollment_api.py``      — AJAX JSON endpoints for the dynamic form

All public symbols are re-exported from here so that ``urls.py`` (and any
other caller) can continue to import from ``apps.enrollments.views`` without
needing to know the internal module structure.

Belongs to: UniAbsences — enrollments app.
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
