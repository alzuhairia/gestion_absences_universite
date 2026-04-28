"""
Modèles sécurité : UserSession (limite sessions simultanées) et TwoFactorBackupCode.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserSession(models.Model):
    """
    Suivi des sessions actives par utilisateur.
    Limite le nombre de sessions simultanées (MAX_SESSIONS_PER_USER)
    en supprimant les plus anciennes au-delà du seuil lors de chaque connexion.
    """

    MAX_SESSIONS_PER_USER = 3

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_sessions",
        verbose_name=_("Utilisateur"),
    )
    session_key = models.CharField(
        max_length=40,
        unique=True,
        verbose_name=_("Clé de session"),
    )
    ip_address = models.GenericIPAddressField(
        verbose_name=_("Adresse IP"),
    )
    user_agent = models.TextField(
        blank=True,
        default="",
        verbose_name=_("User-Agent"),
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Date de création"),
    )

    class Meta:
        db_table = "user_session"
        app_label = "accounts"
        verbose_name = _("Session utilisateur")
        verbose_name_plural = _("Sessions utilisateur")
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["user", "-created_at"],
                name="usersession_user_created_idx",
            ),
        ]

    def __str__(self):
        return f"Session {self.session_key[:8]}… — {self.user}"


class TwoFactorBackupCode(models.Model):
    """
    Code de secours à usage unique pour la 2FA.
    Généré par lot de 8 lors de l'activation de la 2FA.
    Seul le hash est stocké — le code en clair est affiché une seule fois.
    """

    CODES_PER_BATCH = 8

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="backup_codes",
        verbose_name=_("Utilisateur"),
    )
    code_hash = models.CharField(
        max_length=255,
        verbose_name=_("Hash du code"),
        help_text=_("Hash Django (make_password). Le code en clair n'est jamais stocké."),
    )
    used = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Utilisé"),
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Date d'utilisation"),
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Date de création"),
    )

    class Meta:
        db_table = "two_factor_backup_code"
        app_label = "accounts"
        verbose_name = _("Code de secours 2FA")
        verbose_name_plural = _("Codes de secours 2FA")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "used"], name="tfbc_user_used_idx"),
        ]

    def __str__(self):
        state = "utilisé" if self.used else "actif"
        return f"BackupCode {self.user.email} ({state})"
