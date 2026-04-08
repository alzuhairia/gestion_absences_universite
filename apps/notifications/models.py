"""
FICHIER : apps/notifications/models.py
RESPONSABILITE : Notifications in-app et deduplication des emails
FONCTIONNALITES PRINCIPALES :
  - Notification : notification in-app (INTERNE, ALERTE, INFO) avec statut lu/non-lu
  - EmailLog : anti-doublon email via digest SHA-256 + fenetre de cooldown
DEPENDANCES CLES : accounts.User
"""

import hashlib

from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models
from django.utils import timezone


# ========================================================================== #
#                        NOTIFICATION IN-APP                                 #
# ========================================================================== #


class Notification(models.Model):
    """
    Modèle représentant une notification envoyée à un utilisateur.
    """

    TYPE_CHOICES = [
        ("INTERNE", "Interne"),
        ("ALERTE", "Alerte"),
        ("INFO", "Information"),
    ]

    id_notification = models.AutoField(primary_key=True, db_column="id_notification")
    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.CASCADE,  # Supprimer les notifications si l'utilisateur est supprimé
        db_column="id_utilisateur",
        verbose_name="Utilisateur",
        related_name="notifications",
    )
    message = models.TextField(
        db_column="message",
        verbose_name="Message",
        help_text="Contenu de la notification",
        validators=[MaxLengthValidator(5000)],
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="INFO",
        db_column="type",
        verbose_name="Type",
        db_index=True,
    )
    lue = models.BooleanField(
        default=False,
        db_column="lue",
        verbose_name="Lu",
        db_index=True,
        help_text="Indique si la notification a été lue",
    )
    date_envoi = models.DateTimeField(
        auto_now_add=True,
        db_column="date_envoi",
        verbose_name="Date d'envoi",
        db_index=True,
    )

    class Meta:
        managed = True
        db_table = "notification"
        app_label = "notifications"
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ["-date_envoi", "-id_notification"]
        indexes = [
            models.Index(fields=["id_utilisateur", "lue", "date_envoi"]),
            models.Index(fields=["type", "date_envoi"]),
        ]

    def __str__(self):
        return f"Notification pour {self.id_utilisateur} - {self.date_envoi}"


# ========================================================================== #
#                     DEDUPLICATION EMAIL (EmailLog)                          #
# ========================================================================== #


class EmailLog(models.Model):
    """
    Tracks sent emails to prevent duplicate spam.

    A SHA-256 digest is computed from (recipient_email, event_type, event_key)
    and stored with a timestamp.  Before sending, we check whether the same
    digest was already created within the cooldown window.
    """

    digest = models.CharField(max_length=64, unique=True, db_index=True)
    recipient_email = models.EmailField()
    event_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        managed = True
        db_table = "email_log"
        app_label = "notifications"
        indexes = [
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} → {self.recipient_email} ({self.created_at})"

    @classmethod
    def make_digest(cls, email, event_type, event_key):
        """Build a deterministic SHA-256 digest for deduplication."""
        raw = f"{email}|{event_type}|{event_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def already_sent(cls, email, event_type, event_key, cooldown_hours=24):
        """Return True if an email with the same signature was sent within the cooldown."""
        digest = cls.make_digest(email, event_type, event_key)
        cutoff = timezone.now() - timezone.timedelta(hours=cooldown_hours)
        return cls.objects.filter(digest=digest, created_at__gte=cutoff).exists()

    @classmethod
    def record(cls, email, event_type, event_key):
        """
        Record that an email was sent.

        On collision the existing row is preserved as-is — we deliberately do
        NOT reset ``created_at``, otherwise a duplicate send would silently
        push the cooldown window forward and hide the incident.

        Note: this method is retained for backwards compatibility. The
        race-free path is ``send_with_dedup`` in ``apps.notifications.email``,
        which claims the slot via INSERT-or-conditional-UPDATE before sending.
        """
        digest = cls.make_digest(email, event_type, event_key)
        cls.objects.get_or_create(
            digest=digest,
            defaults={
                "recipient_email": email,
                "event_type": event_type,
            },
        )
