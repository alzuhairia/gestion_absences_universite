"""
FICHIER : apps/absences/views/professor_views.py
RESPONSABILITE : Re-export centralisé des vues professeur pour la saisie des présences.

Organisation :
  professor_session.py    — session_create (création + choix du mode) + validate_session
  professor_attendance.py — mark_absence (formulaire complet) + mark_absence_htmx (HTMX)
"""

from .professor_session import session_create, validate_session  # noqa: F401
from .professor_attendance import mark_absence, mark_absence_htmx  # noqa: F401
