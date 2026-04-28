"""
FICHIER : apps/absences/views/professor_attendance.py
RESPONSABILITE : Re-export hub — saisie des présences (appel manuel)

Organisation :
  professor_attendance_form.py  — mark_absence (formulaire complet)
  professor_attendance_htmx.py  — mark_absence_htmx (endpoint HTMX)
"""

from .professor_attendance_form import mark_absence  # noqa: F401
from .professor_attendance_htmx import mark_absence_htmx  # noqa: F401
