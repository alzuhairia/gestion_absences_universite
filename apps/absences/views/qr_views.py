"""
QR attendance system hub — apps/absences/views/qr_views.py

Re-export hub that aggregates all QR attendance view symbols into a single
namespace so that ``absences/urls.py`` can import without knowing the
internal sub-module layout.

Sub-modules
-----------
``qr_utils.py``    — GPS helpers, QR image generation, scan logging (shared).
``qr_professor.py`` — ``qr_generate``, ``qr_dashboard``, ``qr_refresh_token``,
                      ``qr_finalize``.
``qr_student.py``  — ``qr_scan`` (GPS anti-fraud student scan endpoint).

Part of the UniAbsences absences system.
"""

from .qr_professor import (  # noqa: F401
    qr_dashboard,
    qr_finalize,
    qr_generate,
    qr_refresh_token,
)
from .qr_student import qr_scan  # noqa: F401
