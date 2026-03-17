"""
Reusable email utility for UniAbsences notifications.

Features:
    - HTML email templates rendered via Django template engine
    - Plain-text fallback for all emails
    - Duplicate prevention via EmailLog model (configurable cooldown)
    - Thread-based async sending (non-blocking)

Usage:
    from apps.notifications.email import send_notification_email
    send_notification_email(user, subject, body, html_body=html)

Configuration:
    Dev:  EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend (default)
    Prod: Set EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
          plus EMAIL_HOST_USER / EMAIL_HOST_PASSWORD in .env

Emails never raise — failures are logged silently.
"""

import logging
import threading

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


# ─── Core send functions ────────────────────────────────────────────────────


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

    Returns:
        Number of emails successfully sent.
    """
    sent = 0
    for user in recipient_users:
        if send_notification_email(user, subject, body, html_body):
            sent += 1
    return sent


def send_email_async(recipient_user, subject, body, html_body=None):
    """
    Send an email in a background thread. Fire-and-forget.
    Useful for non-critical notifications where blocking the request is undesirable.
    """
    if not recipient_user or not getattr(recipient_user, "email", None):
        return
    if not getattr(recipient_user, "actif", True):
        return

    def _send():
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_user.email],
                html_message=html_body,
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Async email failed for %s (user_id=%s)",
                recipient_user.email,
                getattr(recipient_user, "pk", "?"),
            )

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()


def send_with_dedup(recipient_user, subject, body, html_body, event_type, event_key,
                    cooldown_hours=24):
    """
    Send an email only if the same (recipient, event_type, event_key) was NOT
    already sent within the cooldown window.  Records the send in EmailLog.

    Returns True if sent, False if skipped or failed.
    """
    from apps.notifications.models import EmailLog

    email = getattr(recipient_user, "email", None)
    if not email:
        return False

    if EmailLog.already_sent(email, event_type, event_key, cooldown_hours):
        logger.debug(
            "Dedup: skipping %s email to %s (key=%s)", event_type, email, event_key
        )
        return False

    sent = send_notification_email(recipient_user, subject, body, html_body)
    if sent:
        EmailLog.record(email, event_type, event_key)
    return sent


# ─── HTML template rendering helper ─────────────────────────────────────────


def _render_html(template_name, context):
    """Render an HTML email template. Returns None on error (graceful fallback)."""
    try:
        return render_to_string(template_name, context)
    except Exception:
        logger.exception("Failed to render email template %s", template_name)
        return None


# ─── Email template builders ────────────────────────────────────────────────
# Return (subject, body, html_body) tuples ready for send_notification_email().


def build_threshold_exceeded_email(student, course_name, taux, seuil):
    """Email sent to student when absence threshold is exceeded."""
    subject = f"[UniAbsences] ALERTE \u2014 Seuil d'absence d\u00e9pass\u00e9 pour {course_name}"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
        "taux": f"{taux:.1f}",
        "seuil": seuil,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Votre taux d'absence pour le cours \u00ab {course_name} \u00bb "
        f"a atteint {context['taux']}%, d\u00e9passant le seuil autoris\u00e9 de {seuil}%.\n\n"
        f"Votre acc\u00e8s \u00e0 l'examen pour ce cours est d\u00e9sormais bloqu\u00e9.\n\n"
        f"Si vous pensez qu'il s'agit d'une erreur, veuillez contacter le secr\u00e9tariat.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/threshold_exceeded.html", context)
    return subject, body, html_body


def build_threshold_exceeded_professor_email(professor, student, course_name, taux, seuil):
    """Email sent to professor when a student in their course exceeds the threshold."""
    subject = f"[UniAbsences] \u00c9tudiant bloqu\u00e9 \u2014 {student.get_full_name()} ({course_name})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "student_email": student.email,
        "course_name": course_name,
        "taux": f"{taux:.1f}",
        "seuil": seuil,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"L'\u00e9tudiant {context['student_name']} ({student.email}) a d\u00e9pass\u00e9 le seuil "
        f"d'absence pour votre cours \u00ab {course_name} \u00bb.\n\n"
        f"Taux actuel : {context['taux']}% (seuil : {seuil}%)\n"
        f"L'acc\u00e8s \u00e0 l'examen a \u00e9t\u00e9 automatiquement bloqu\u00e9.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/threshold_exceeded_professor.html", context)
    return subject, body, html_body


def build_eligibility_restored_email(student, course_name):
    """Email sent to student when eligibility is restored."""
    subject = f"[UniAbsences] \u00c9ligibilit\u00e9 restaur\u00e9e \u2014 {course_name}"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Vous \u00eates \u00e0 nouveau \u00e9ligible \u00e0 l'examen pour le cours \u00ab {course_name} \u00bb.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/eligibility_restored.html", context)
    return subject, body, html_body


def build_justification_submitted_professor_email(professor, student, course_code, absence_date):
    """Email sent to professor when a student submits a justification."""
    subject = f"[UniAbsences] Justificatif soumis \u2014 {student.get_full_name()} ({course_code})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "student_email": student.email,
        "course_code": course_code,
        "absence_date": absence_date,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"L'\u00e9tudiant {context['student_name']} ({student.email}) a soumis un justificatif "
        f"pour son absence du {absence_date} dans votre cours {course_code}.\n\n"
        f"Le secr\u00e9tariat proc\u00e9dera \u00e0 la validation.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/justification_submitted.html", context)
    return subject, body, html_body


def build_justification_decision_email(student, course_code, absence_date, approved, motif=""):
    """Email sent to student when justification is approved or rejected."""
    decision = "ACCEPT\u00c9E" if approved else "REFUS\u00c9E"
    subject = f"[UniAbsences] Justification {decision} \u2014 {course_code} ({absence_date})"
    context = {
        "student_name": student.get_full_name(),
        "course_code": course_code,
        "absence_date": absence_date,
        "approved": approved,
        "decision": decision,
        "motif": motif,
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Votre justification pour l'absence du {absence_date} "
        f"dans le cours {course_code} a \u00e9t\u00e9 {decision}.\n"
    )
    if not approved and motif:
        body += f"\nMotif : {motif}\n"
    body += f"\n\u2014 UniAbsences Notification System"
    html_body = _render_html("emails/justification_decision.html", context)
    return subject, body, html_body


def build_justification_decision_professor_email(professor, student, course_code, absence_date, approved):
    """Email sent to professor when a justification in their course is decided."""
    decision = "accept\u00e9e" if approved else "refus\u00e9e"
    subject = f"[UniAbsences] Justification {decision} \u2014 {student.get_full_name()} ({course_code})"
    context = {
        "professor_name": professor.get_full_name(),
        "student_name": student.get_full_name(),
        "course_code": course_code,
        "absence_date": absence_date,
        "approved": approved,
        "decision": decision,
    }
    body = (
        f"Bonjour {context['professor_name']},\n\n"
        f"La justification de {context['student_name']} pour l'absence du {absence_date} "
        f"dans votre cours {course_code} a \u00e9t\u00e9 {decision} par le secr\u00e9tariat.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/justification_decision_professor.html", context)
    return subject, body, html_body


def build_absence_recorded_email(student, course_name, absence_date, taux):
    """Email sent to student when a professor records an absence."""
    subject = f"[UniAbsences] Absence enregistr\u00e9e \u2014 {course_name} ({absence_date})"
    context = {
        "student_name": student.get_full_name(),
        "course_name": course_name,
        "absence_date": absence_date,
        "taux": f"{taux:.1f}",
    }
    body = (
        f"Bonjour {context['student_name']},\n\n"
        f"Une absence a \u00e9t\u00e9 enregistr\u00e9e pour le cours \u00ab {course_name} \u00bb "
        f"le {absence_date}.\n\n"
        f"Votre taux d'absence actuel est de {context['taux']}%.\n\n"
        f"Si vous pensez qu'il s'agit d'une erreur, veuillez contacter votre professeur "
        f"ou soumettre un justificatif.\n\n"
        f"\u2014 UniAbsences Notification System"
    )
    html_body = _render_html("emails/absence_recorded.html", context)
    return subject, body, html_body


def build_weekly_summary_email(secretary, summary_data):
    """
    Email sent to secretaries with weekly absence statistics.

    Args:
        secretary: User instance (secretary)
        summary_data: dict with keys:
            - week_start, week_end: date strings
            - total_absences: int
            - new_blocked: int
            - pending_justifications: int
            - courses_at_risk: list of {course_name, at_risk_count}
    """
    subject = (
        f"[UniAbsences] R\u00e9sum\u00e9 hebdomadaire des absences "
        f"({summary_data['week_start']} \u2014 {summary_data['week_end']})"
    )
    context = {
        "secretary_name": secretary.get_full_name(),
        **summary_data,
    }
    body = (
        f"Bonjour {context['secretary_name']},\n\n"
        f"Voici le r\u00e9sum\u00e9 hebdomadaire des absences "
        f"({summary_data['week_start']} \u2014 {summary_data['week_end']}) :\n\n"
        f"  \u2022 Absences enregistr\u00e9es : {summary_data['total_absences']}\n"
        f"  \u2022 Nouveaux blocages : {summary_data['new_blocked']}\n"
        f"  \u2022 Justificatifs en attente : {summary_data['pending_justifications']}\n\n"
    )
    if summary_data.get("courses_at_risk"):
        body += "Cours avec \u00e9tudiants \u00e0 risque :\n"
        for c in summary_data["courses_at_risk"]:
            body += f"  \u2022 {c['course_name']} : {c['at_risk_count']} \u00e9tudiant(s)\n"
    body += f"\n\u2014 UniAbsences Notification System"
    html_body = _render_html("emails/weekly_summary.html", context)
    return subject, body, html_body
