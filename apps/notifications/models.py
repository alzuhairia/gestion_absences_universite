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
        """Métadonnées Django : table ``notification``, tri chronologique inverse et index lus/non-lus."""

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
        """Représentation lisible identifiant le destinataire et la date d'envoi."""
        return f"Notification pour {self.id_utilisateur} - {self.date_envoi}"


# ========================================================================== #
#                     DEDUPLICATION EMAIL (EmailLog)                          #
# ========================================================================== #


class EmailLog(models.Model):
    """
    Suit les emails envoyés afin d'empêcher les doublons de spam.

    Un digest SHA-256 est calculé à partir de (recipient_email, event_type, event_key)
    et stocké avec un horodatage. Avant l'envoi, on vérifie si le même digest a déjà
    été créé dans la fenêtre de cooldown.
    """

    digest = models.CharField(max_length=64, unique=True, db_index=True)
    recipient_email = models.EmailField()
    event_type = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """Métadonnées Django : table ``email_log`` et index sur ``created_at`` pour le cooldown."""

        managed = True
        db_table = "email_log"
        app_label = "notifications"
        indexes = [
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        """Représentation lisible : type d'événement → destinataire (date)."""
        return f"{self.event_type} → {self.recipient_email} ({self.created_at})"

    @classmethod
    def make_digest(cls, email, event_type, event_key):
        """Construit un digest SHA-256 déterministe pour la déduplication."""
        raw = f"{email}|{event_type}|{event_key}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def already_sent(cls, email, event_type, event_key, cooldown_hours=24):
        """Retourne True si un email avec la même signature a été envoyé pendant la période de cooldown."""
        digest = cls.make_digest(email, event_type, event_key)
        cutoff = timezone.now() - timezone.timedelta(hours=cooldown_hours)
        return cls.objects.filter(digest=digest, created_at__gte=cutoff).exists()

    @classmethod
    def record(cls, email, event_type, event_key):
        """
        Enregistre qu'un email a été envoyé.

        En cas de collision, la ligne existante est conservée telle quelle — on ne
        réinitialise PAS volontairement ``created_at``, sinon un envoi en double
        repousserait silencieusement la fenêtre de cooldown et masquerait l'incident.

        Note : cette méthode est conservée pour la rétrocompatibilité. Le chemin
        race-free est ``send_with_dedup`` dans ``apps.notifications.email``,
        qui revendique le slot via INSERT-or-conditional-UPDATE avant l'envoi.
        """
        digest = cls.make_digest(email, event_type, event_key)
        cls.objects.get_or_create(
            digest=digest,
            defaults={
                "recipient_email": email,
                "event_type": event_type,
            },
        )
