"""
Professor attendance views hub — apps/absences/views/professor_attendance.py

Re-export hub that aggregates manual attendance-marking view functions from
the two sub-modules so that ``absences/urls.py`` imports from a single stable
location.

Sub-modules
-----------
``professor_attendance_form.py``
    ``mark_absence`` — full-page attendance form for marking an entire class
    present or absent in a single POST submission.

``professor_attendance_htmx.py``
    ``mark_absence_htmx`` — lightweight HTMX endpoint that updates a single
    student row in real time without a full page reload.

Both symbols are re-exported with ``noqa: F401`` so that static analysis
tools do not flag the imports as unused; they are intentionally exposed as
part of this package's public API.

Part of the UniAbsences absences system.
"""

from .professor_attendance_form import mark_absence  # noqa: F401
from .professor_attendance_htmx import mark_absence_htmx  # noqa: F401
