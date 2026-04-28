"""
FICHIER : apps/notifications/email.py
RESPONSABILITE : Re-export centralisé du système d'emails de notification.

Organisation :
  email_core.py     — infrastructure d'envoi (send_*, deduplication, pool de threads)
  email_builders.py — constructeurs d'emails par type de notification
"""

from .email_core import (  # noqa: F401
    _render_html,
    send_email_async,
    send_notification_email,
    send_notification_email_bulk,
    send_with_dedup,
)
from .email_builders import (  # noqa: F401
    build_absence_recorded_email,
    build_eligibility_restored_email,
    build_justification_decision_email,
    build_justification_decision_professor_email,
    build_justification_submitted_professor_email,
    build_threshold_exceeded_email,
    build_threshold_exceeded_professor_email,
    build_weekly_summary_email,
)
