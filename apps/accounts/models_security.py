"""
Modèles liés à la sécurité pour le système de comptes UniAbsences.

Ce module contient deux modèles qui supportent la couche de sécurité de
l'application :

UserSession
    Suit chaque session de navigateur active par utilisateur et applique une
    limite de sessions par utilisateur, évinçant automatiquement les sessions
    les plus anciennes lorsque la limite est dépassée. Cela fournit une liste
    auditable de connexions actives et empêche une prolifération illimitée
    de sessions.

TwoFactorBackupCode
    Stocke les codes de récupération à usage unique émis lorsqu'un utilisateur
    active l'authentification à deux facteurs basée sur TOTP. Seul le hash
    bcrypt de chaque code est persisté — le texte en clair est montré à
    l'utilisateur exactement une fois puis abandonné.

Responsabilités
---------------
- Persister et indexer les enregistrements de sessions actives (clé, IP,
  user-agent, horodatage).
- Appliquer ``UserSession.MAX_SESSIONS_PER_USER`` au niveau applicatif
  (appliqué dans ``RateLimitedLoginView.form_valid``).
- Stocker les codes de secours 2FA hashés et enregistrer quand chaque code
  a été consommé.

Fait partie du système de comptes UniAbsences.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserSession(models.Model):
    """
    Représente une seule session de navigateur active appartenant à un utilisateur.

    Une instance est créée dans ``RateLimitedLoginView.form_valid`` à chaque
    connexion réussie. Lorsque le nombre de sessions actives pour un
    utilisateur dépasse ``MAX_SESSIONS_PER_USER``, les entrées les plus
    anciennes — ainsi que leurs enregistrements Django ``Session``
    correspondants — sont supprimées automatiquement dans une transaction
    de base de données.

    Double finalité
    ---------------
    Audit de sécurité
        Les administrateurs peuvent voir quelles adresses IP et quels
        navigateurs ont actuellement des sessions actives pour n'importe
        quel compte.
    Application de la limite de sessions
        Empêche un seul compte d'accumuler un nombre illimité de sessions
        concurrentes (défense contre le partage d'identifiants et les
        sessions oubliées à longue durée de vie).

    Ordering
    --------
    Les enregistrements sont triés du plus récent au plus ancien
    (``-created_at``) afin que le slicing
    ``UserSession.objects.filter(user=...).order_by('-created_at')[N:]``
    retourne les sessions devant être évincées.
    """

    MAX_SESSIONS_PER_USER = 3
    """
    Nombre maximum de sessions simultanées autorisées par compte utilisateur.

    Lorsqu'une nouvelle connexion fait passer le compteur au-dessus de cette
    valeur, les sessions les plus anciennes (au-delà de ce seuil) sont
    supprimées avec leurs enregistrements de session Django afin que la base
    de données n'accumule pas de données obsolètes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="user_sessions",
        verbose_name=_("Utilisateur"),
        help_text=_("Utilisateur propriétaire de cette session."),
    )
    session_key = models.CharField(
        max_length=40,
        unique=True,
        verbose_name=_("Clé de session"),
        help_text=_("Clé primaire de la session Django correspondante."),
    )
    ip_address = models.GenericIPAddressField(
        verbose_name=_("Adresse IP"),
        help_text=_("Adresse IP du client au moment de la connexion."),
    )
    user_agent = models.TextField(
        blank=True,
        default="",
        verbose_name=_("User-Agent"),
        help_text=_("En-tête HTTP User-Agent du navigateur client (tronqué à 500 car.)."),
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Date de création"),
        help_text=_("Horodatage de la connexion initiale."),
    )

    class Meta:
        """Métadonnées Django : table ``user_session``, tri par création et index d'éviction."""

        db_table = "user_session"
        app_label = "accounts"
        verbose_name = _("Session utilisateur")
        verbose_name_plural = _("Sessions utilisateur")
        # Sessions les plus récentes en premier afin que le slicing [N:] donne les sessions à évincer.
        ordering = ["-created_at"]
        indexes = [
            # Index composite utilisé par la requête d'application de la limite de sessions :
            # filter(user=...).order_by('-created_at')
            models.Index(
                fields=["user", "-created_at"],
                name="usersession_user_created_idx",
            ),
        ]

    def __str__(self):
        """
        Retourne un identifiant de session court et lisible.

        Returns:
            str: Les 8 premiers caractères de la clé de session suivis de
                 la représentation chaîne de l'utilisateur.
        """
        return f"Session {self.session_key[:8]}… — {self.user}"


class TwoFactorBackupCode(models.Model):
    """
    Un seul code de récupération à usage unique pour l'accès au compte 2FA.

    Généré par lots de ``CODES_PER_BATCH`` par ``_generate_backup_codes``
    chaque fois qu'un utilisateur active la 2FA ou demande explicitement la
    régénération des codes. Le code en clair est affiché à l'utilisateur
    exactement une fois immédiatement après la génération et n'est **jamais
    stocké**. Seul le hash Django ``make_password`` (bcrypt par défaut) est
    persisté dans ``code_hash``.

    Flux de vérification
    --------------------
    Lorsqu'un utilisateur soumet un code de secours lors de la vérification 2FA :

    1. La chaîne soumise est normalisée (mise en majuscules, alphanumérique
       uniquement) via ``_normalize_backup_code``.
    2. Tous les hash inutilisés pour cet utilisateur sont récupérés sous un
       verrou ``select_for_update`` pour empêcher une double utilisation concurrente.
    3. Chaque hash est comparé au candidat à l'aide de ``check_password``
       (comparaison à temps constant — pas de sortie anticipée lors du
       premier non-match afin d'éviter les canaux temporels secondaires).
    4. En cas de match, ``used=True`` et ``used_at`` sont définis afin que
       le code ne puisse pas être réutilisé (pattern classique de jeton à usage unique).
    """

    CODES_PER_BATCH = 8
    """
    Nombre de codes de secours générés par lot.

    Tous les codes existants (utilisés ou non) sont supprimés atomiquement
    avant la création du nouveau lot, garantissant qu'il n'y a jamais
    d'ambiguïté sur les codes valides.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="backup_codes",
        verbose_name=_("Utilisateur"),
        help_text=_("Utilisateur auquel appartient ce code de secours."),
    )
    code_hash = models.CharField(
        max_length=255,
        verbose_name=_("Hash du code"),
        help_text=_(
            "Hash Django (make_password / bcrypt). "
            "Le code en clair n'est jamais stocké."
        ),
    )
    used = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name=_("Utilisé"),
        help_text=_("True si ce code a déjà été consommé et ne peut plus être réutilisé."),
    )
    used_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Date d'utilisation"),
        help_text=_("Horodatage de la première (et unique) utilisation de ce code."),
    )
    created_at = models.DateTimeField(
        default=timezone.now,
        verbose_name=_("Date de création"),
        help_text=_("Horodatage de la génération de ce code."),
    )

    class Meta:
        """Métadonnées Django : table ``two_factor_backup_code`` et index pour la vérification 2FA."""

        db_table = "two_factor_backup_code"
        app_label = "accounts"
        verbose_name = _("Code de secours 2FA")
        verbose_name_plural = _("Codes de secours 2FA")
        ordering = ["-created_at"]
        indexes = [
            # Index composite utilisé par la requête de vérification des codes de secours :
            # filter(user=..., used=False)
            models.Index(fields=["user", "used"], name="tfbc_user_used_idx"),
        ]

    def __str__(self):
        """
        Retourne l'email de l'utilisateur et si ce code a déjà été consommé.

        Returns:
            str: Résumé lisible, par ex.
                 "BackupCode user@example.com (actif)"
        """
        state = "utilisé" if self.used else "actif"
        return f"BackupCode {self.user.email} ({state})"
