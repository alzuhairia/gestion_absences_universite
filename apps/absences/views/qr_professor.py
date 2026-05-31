"""
Professor QR-code views hub — apps/absences/views/qr_professor.py

Re-export hub that aggregates all professor-facing QR attendance view functions
into a single stable namespace so that ``absences/urls.py`` can import without
knowing the internal sub-module layout.

Sub-modules
-----------
``qr_professor_generate.py``
    ``qr_generate`` — create a ``Seance`` and issue a signed ``QRAttendanceToken``;
    redirect to the live dashboard.

``qr_professor_session.py``
    ``qr_dashboard``     — real-time scan dashboard (HTMX-polled).
    ``qr_refresh_token`` — rotate the active QR token without losing existing scans.
    ``qr_finalize``      — close the session: mark non-scanners absent and lock.

All symbols are re-exported with ``noqa: F401`` so that static analysis tools
do not flag the imports as unused; they are intentionally part of this
package's public API.

Part of the UniAbsences absences system.
"""

from .qr_professor_generate import qr_generate  # noqa: F401
from .qr_professor_session import (  # noqa: F401
    qr_dashboard,
    qr_finalize,
    qr_refresh_token,
)
