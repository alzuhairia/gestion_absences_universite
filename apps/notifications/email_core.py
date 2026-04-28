"""
Infrastructure d'envoi d'emails de notification UniAbsences.

Fonctions :
  - send_notification_email      : envoi synchrone à un destinataire (ne lève jamais)
  - send_notification_email_bulk : envoi synchrone à plusieurs destinataires
  - send_email_async             : envoi via pool de threads (fire-and-forget)
  - send_with_dedup              : envoi avec déduplication via EmailLog (race-free)
  - _render_html                 : rendu d'un template HTML email (helper interne)

Configuration :
  Dev  : EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend (défaut)
  Prod : EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend + .env
"""
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.core.mail import send_mail
from django.db import IntegrityError, transaction
from django.template.loader import render_to_string
from django.utils import timezone

logger = logging.getLogger(__name__)

# Bounded thread pool for fire-and-forget async email sending.
# Prevents thread explosion when bulk operations (e.g. mark_absence on 200 students)
# trigger many emails at once. Daemon=True so workers don't block process shutdown.
_EMAIL_EXECUTOR = ThreadPoolExecutor(
    max_workers=getattr(settings, "EMAIL_ASYNC_MAX_WORKERS", 5),
    thread_name_prefix="email-async",
)


def send_notification_email(recipient_user, subject, body, html_body=None):
    """
    Send a single notification email. Never raises.

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
    Send an email via a bounded background thread pool. Fire-and-forget.

    Uses a shared ThreadPoolExecutor so that bulk operations cannot exhaust
    process resources. Submissions beyond pool capacity queue instead of
    spawning unbounded threads.
    """
    if not recipient_user or not getattr(recipient_user, "email", None):
        return
    if not getattr(recipient_user, "actif", True):
        return

    recipient_email = recipient_user.email
    recipient_pk = getattr(recipient_user, "pk", "?")

    def _send():
        try:
            send_mail(
                subject=subject,
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                html_message=html_body,
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Async email failed for %s (user_id=%s)",
                recipient_email,
                recipient_pk,
            )

    try:
        _EMAIL_EXECUTOR.submit(_send)
    except RuntimeError:
        # Executor was shut down (e.g. during process teardown). Fall back to
        # a one-shot daemon thread so we don't drop the email entirely.
        threading.Thread(target=_send, daemon=True).start()


def send_with_dedup(recipient_user, subject, body, html_body, event_type, event_key,
                    cooldown_hours=24):
    """
    Send an email only if the same (recipient, event_type, event_key) was NOT
    already sent within the cooldown window.  Records the send in EmailLog.

    Race-free: the EmailLog row is claimed *before* sending, inside an atomic
    block, so two concurrent callers cannot both pass the check and both send.

    Returns True if sent, False if skipped or failed.
    """
    from apps.notifications.models import EmailLog

    email = getattr(recipient_user, "email", None)
    if not email:
        return False

    digest = EmailLog.make_digest(email, event_type, event_key)
    cutoff = timezone.now() - timezone.timedelta(hours=cooldown_hours)

    try:
        with transaction.atomic():
            existing = EmailLog.objects.filter(digest=digest).first()
            if existing is None:
                try:
                    EmailLog.objects.create(
                        digest=digest,
                        recipient_email=email,
                        event_type=event_type,
                    )
                except IntegrityError:
                    logger.debug(
                        "Dedup race: another worker claimed %s email to %s (key=%s)",
                        event_type, email, event_key,
                    )
                    return False
            elif existing.created_at >= cutoff:
                logger.debug(
                    "Dedup: skipping %s email to %s (key=%s)",
                    event_type, email, event_key,
                )
                return False
            else:
                claimed = EmailLog.objects.filter(
                    digest=digest, created_at=existing.created_at
                ).update(created_at=timezone.now())
                if not claimed:
                    logger.debug(
                        "Dedup race: another worker refreshed %s email to %s (key=%s)",
                        event_type, email, event_key,
                    )
                    return False
    except Exception:
        logger.exception(
            "Failed to claim dedup slot for %s email to %s", event_type, email
        )
        return False

    return send_notification_email(recipient_user, subject, body, html_body)


def _render_html(template_name, context):
    """Render an HTML email template. Returns None on error (graceful fallback)."""
    try:
        return render_to_string(template_name, context)
    except Exception:
        logger.exception("Failed to render email template %s", template_name)
        return None
