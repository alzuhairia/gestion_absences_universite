"""
Professor views hub — apps/absences/views/professor_views.py

Re-export hub that aggregates all professor-facing absence and attendance view
functions into a single stable namespace, so that ``absences/urls.py`` can
import all professor symbols from one location without depending on the
internal sub-module layout.

Sub-modules
-----------
``professor_session.py``
    Session lifecycle management:
      - ``session_create``   — unified entry point (create session + mode selection).
      - ``validate_session`` — permanently lock a session (read-only after this).

``professor_attendance.py``  (itself a hub for two sub-modules)
    Attendance recording:
      - ``mark_absence``      — full-page attendance form (GET/POST).
      - ``mark_absence_htmx`` — HTMX partial endpoint for real-time row updates.

All symbols are re-exported with ``noqa: F401`` so linters do not flag the
imports as unused; they are intentionally part of this package's public API.

Part of the UniAbsences absences system.
"""

from .professor_session import session_create, validate_session  # noqa: F401
from .professor_attendance import mark_absence, mark_absence_htmx  # noqa: F401
