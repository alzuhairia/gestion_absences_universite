"""
Package initializer for the absences views layer — apps/absences/views/__init__.py

This package organizes all HTTP view functions for the UniAbsences absence
management system.  Each sub-module is responsible for a distinct role or
feature area, keeping individual files small and focused.

Sub-module layout
-----------------
student_views.py
    Student-facing views: absence details, justification upload, and document
    download.

professor_views.py  (re-export hub)
    Aggregates professor attendance views from two sub-modules:
      - professor_session.py      : ``session_create`` (unified session entry
                                    point, manual or QR mode selection) and
                                    ``validate_session`` (permanent lock).
      - professor_attendance.py   : re-export hub for the two marking views:
          - professor_attendance_form.py  : ``mark_absence`` (full-page form).
          - professor_attendance_htmx.py  : ``mark_absence_htmx`` (HTMX partial).

qr_views.py  (re-export hub)
    Aggregates all QR attendance views from three sub-modules:
      - qr_utils.py          : GPS helpers (Haversine), QR image generation,
                               SHA-256 token hashing, and scan-attempt logging.
      - qr_professor.py      : ``qr_generate``, ``qr_dashboard``,
                               ``qr_refresh_token``, ``qr_finalize``.
      - qr_student.py        : ``qr_scan`` (GPS anti-fraud student endpoint).

secretary_views.py  (re-export hub)
    Aggregates secretariat views from two sub-modules:
      - secretary_justification.py     : ``review_justification``,
                                         ``validation_list``,
                                         ``process_justification``,
                                         ``justified_absences_list``.
      - secretary_absence_encoding.py  : ``create_justified_absence``,
                                         ``student_absence_history_api``.

admin_views.py
    Direct absence record editing by the secretariat (``edit_absence``).

All public symbols are re-exported here so that ``absences/urls.py`` can
import from the single stable path ``apps.absences.views.*`` without
depending on the internal sub-module layout.

Part of the UniAbsences absences system.
"""

from .student_views import (
    absence_details,
    upload_justification,
    download_justification,
)
from .professor_views import (
    session_create,
    mark_absence,
    mark_absence_htmx,
    validate_session,
)
from .qr_views import (
    qr_generate,
    qr_dashboard,
    qr_refresh_token,
    qr_finalize,
    qr_scan,
)
from .secretary_views import (
    review_justification,
    validation_list,
    process_justification,
    create_justified_absence,
    justified_absences_list,
    student_absence_history_api,
)
from .admin_views import edit_absence

__all__ = [
    "absence_details",
    "upload_justification",
    "download_justification",
    "session_create",
    "mark_absence",
    "mark_absence_htmx",
    "validate_session",
    "review_justification",
    "qr_generate",
    "qr_dashboard",
    "qr_refresh_token",
    "qr_finalize",
    "qr_scan",
    "validation_list",
    "process_justification",
    "create_justified_absence",
    "justified_absences_list",
    "student_absence_history_api",
    "edit_absence",
]
