"""
Reusable email utility for UniAbsences notifications.

Usage:
    from apps.notifications.email import send_notification_email
    send_notification_email(user, subject, message)

Configuration:
    Dev:  EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend (default)
    Prod: Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
          plus EMAIL_HOST_USER / EMAIL_HOST_PASSWORD in .env

Emails never raise — failures are logged silently.
"""

import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_notification_email(recipient_user, subject, body, html_body=None):
    """
    Send a single notification email. Never raises.

    Args:
        recipient_user: User model instance (must have .email and .actif)
        subject: Email subject line
        body: Plain-text email body
        html_body: Optional HTML body (if None, plain text only)

    Returns:
        True if email was sent, False otherwise.
    """
    if not recipient_user or not getattr(recipient_user, "email", None):
        return False

    if not getattr(recipient_user, "actif", True):
        return False

    try:
        send_mail(
            subject=subject,
            message=body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient_user.email],
            html_message=html_body,
            fail_silently=False,
        )
        return True
    except Exception:
        logger.exception(
            "Failed to send email to %s (user_id=%s)",
            recipient_user.email,
            getattr(recipient_user, "pk", "?"),
        )
        return False


def send_notification_email_bulk(recipient_users, subject, body, html_body=None):
    """
    Send the same email to multiple users. Never raises.

    Args:
        recipient_users: iterable of User instances
        subject: Email subject line
        body: Plain-text body
        html_body: Optional HTML body

    Returns:
        Number of emails successfully sent.
    """
    sent = 0
    for user in recipient_users:
        if send_notification_email(user, subject, body, html_body):
            sent += 1
    return sent


# ─── Email template builders ─────────────────────────────────────────────────
# These return (subject, body) tuples ready for send_notification_email().


def build_threshold_exceeded_email(student, course_name, taux, seuil):
    """Email sent to student when absence threshold is exceeded."""
    subject = f"[UniAbsences] ALERTE — Seuil d'absence dépassé pour {course_name}"
    body = (
        f"Bonjour {student.get_full_name()},\n\n"
        f"Votre taux d'absence pour le cours « {course_name} » "
        f"a atteint {taux:.1f}%, dépassant le seuil autorisé de {seuil}%.\n\n"
        f"Votre accès à l'examen pour ce cours est désormais bloqué.\n\n"
        f"Si vous pensez qu'il s'agit d'une erreur, veuillez contacter le secrétariat.\n\n"
        f"— UniAbsences Notification System"
    )
    return subject, body


def build_threshold_exceeded_professor_email(professor, student, course_name, taux, seuil):
    """Email sent to professor when a student in their course exceeds the threshold."""
    subject = f"[UniAbsences] Étudiant bloqué — {student.get_full_name()} ({course_name})"
    body = (
        f"Bonjour {professor.get_full_name()},\n\n"
        f"L'étudiant {student.get_full_name()} ({student.email}) a dépassé le seuil "
        f"d'absence pour votre cours « {course_name} ».\n\n"
        f"Taux actuel : {taux:.1f}% (seuil : {seuil}%)\n"
        f"L'accès à l'examen a été automatiquement bloqué.\n\n"
        f"— UniAbsences Notification System"
    )
    return subject, body


def build_eligibility_restored_email(student, course_name):
    """Email sent to student when eligibility is restored."""
    subject = f"[UniAbsences] Éligibilité restaurée — {course_name}"
    body = (
        f"Bonjour {student.get_full_name()},\n\n"
        f"Vous êtes à nouveau éligible à l'examen pour le cours « {course_name} ».\n\n"
        f"— UniAbsences Notification System"
    )
    return subject, body


def build_justification_submitted_professor_email(professor, student, course_code, absence_date):
    """Email sent to professor when a student submits a justification."""
    subject = f"[UniAbsences] Justificatif soumis — {student.get_full_name()} ({course_code})"
    body = (
        f"Bonjour {professor.get_full_name()},\n\n"
        f"L'étudiant {student.get_full_name()} ({student.email}) a soumis un justificatif "
        f"pour son absence du {absence_date} dans votre cours {course_code}.\n\n"
        f"Le secrétariat procédera à la validation.\n\n"
        f"— UniAbsences Notification System"
    )
    return subject, body


def build_justification_decision_email(student, course_code, absence_date, approved, motif=""):
    """Email sent to student when justification is approved or rejected."""
    decision = "ACCEPTÉE" if approved else "REFUSÉE"
    subject = f"[UniAbsences] Justification {decision} — {course_code} ({absence_date})"
    body = (
        f"Bonjour {student.get_full_name()},\n\n"
        f"Votre justification pour l'absence du {absence_date} "
        f"dans le cours {course_code} a été {decision}.\n"
    )
    if not approved and motif:
        body += f"\nMotif : {motif}\n"
    body += f"\n— UniAbsences Notification System"
    return subject, body


def build_justification_decision_professor_email(professor, student, course_code, absence_date, approved):
    """Email sent to professor when a justification in their course is decided."""
    decision = "acceptée" if approved else "refusée"
    subject = f"[UniAbsences] Justification {decision} — {student.get_full_name()} ({course_code})"
    body = (
        f"Bonjour {professor.get_full_name()},\n\n"
        f"La justification de {student.get_full_name()} pour l'absence du {absence_date} "
        f"dans votre cours {course_code} a été {decision} par le secrétariat.\n\n"
        f"— UniAbsences Notification System"
    )
    return subject, body
