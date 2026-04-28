"""
Package de vues pour la gestion des absences.

Organisation par rôle (chaque fichier = une responsabilité) :
  - student_views.py          : détails d'absence, soumission justificatif, téléchargement
  - professor_views.py        : re-export hub → professor_session + professor_attendance
    - professor_session.py    : session_create (créer séance + choisir mode) + validate_session
    - professor_attendance.py : mark_absence (formulaire complet) + mark_absence_htmx (HTMX)
  - qr_views.py               : re-export hub → qr_professor + qr_student
    - qr_utils.py             : helpers GPS, génération QR, logging (partagés)
    - qr_professor.py         : qr_generate, qr_dashboard, qr_refresh_token, qr_finalize
    - qr_student.py           : qr_scan (anti-fraude GPS, double-scan)
  - secretary_views.py        : re-export hub → secretary_justification + secretary_absence_encoding
    - secretary_justification.py    : review_justification, validation_list, process_justification, justified_absences_list
    - secretary_absence_encoding.py : create_justified_absence, student_absence_history_api
  - admin_views.py            : édition directe d'une absence

Toutes les fonctions restent importables depuis apps.absences.views
pour assurer la compatibilité des URLs.
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
