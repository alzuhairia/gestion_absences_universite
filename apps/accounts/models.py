"""
FICHIER : apps/accounts/models.py
RESPONSABILITE : Modele utilisateur personnalise (4 roles) et manager de creation
FONCTIONNALITES PRINCIPALES :
  - Modele User custom avec email comme identifiant (pas username)
  - 4 roles : ADMIN, SECRETAIRE, PROFESSEUR, ETUDIANT
  - Synchronisation automatique is_staff/is_superuser selon le role
  - Niveau academique (1-3) obligatoire pour les etudiants
  - Flag must_change_password pour mots de passe temporaires
DEPENDANCES CLES : Django AbstractBaseUser, PermissionsMixin
"""

from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class UserManager(BaseUserManager):
    """Manager personnalisé pour le modèle User"""

    def create_user(self, email, nom, prenom, password=None, **extra_fields):
        """Crée et sauvegarde un utilisateur normal"""
        if not email:
            raise ValueError(_("L'adresse email est obligatoire"))
        if not nom:
            raise ValueError(_("Le nom est obligatoire"))
        if not prenom:
            raise ValueError(_("Le prénom est obligatoire"))

        email = self.normalize_email(email)
        role = extra_fields.setdefault("role", self.model.Role.ETUDIANT)
        # Garantit la compatibilité avec la contrainte DB
        # "etudiant_doit_avoir_niveau" quand le niveau n'est pas fourni.
        if role == self.model.Role.ETUDIANT and extra_fields.get("niveau") is None:
            extra_fields["niveau"] = 1
        user = self.model(email=email, nom=nom, prenom=prenom, **extra_fields)
        user.set_password(password)
        user._sync_role_flags()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, nom, prenom, password=None, **extra_fields):
        """Crée et sauvegarde un superutilisateur (admin)"""
        extra_fields.setdefault("role", self.model.Role.ADMIN)
        extra_fields.setdefault("actif", True)
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError(_("Le superutilisateur doit avoir is_staff=True."))
        if extra_fields.get("is_superuser") is not True:
            raise ValueError(_("Le superutilisateur doit avoir is_superuser=True."))

        return self.create_user(email, nom, prenom, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Modèle utilisateur personnalisé pour UniAbsences.

    Ce modèle représente tous les utilisateurs du système (étudiants, professeurs,
    secrétaires, administrateurs). Il est 100% compatible avec la table PostgreSQL
    existante 'utilisateur'.

    IMPORTANT POUR LA SOUTENANCE :
    - Gestion des rôles : 4 rôles distincts avec permissions différentes
    - Sécurité : mots de passe hashés, changement obligatoire pour nouveaux comptes
    - Niveau académique : uniquement pour les étudiants (1, 2 ou 3)
    """

    # ============================================
    # CHAMPS IDENTIFIANT
    # ============================================

    id_utilisateur = models.AutoField(
        primary_key=True, db_column="id_utilisateur", verbose_name=_("ID Utilisateur")
    )
    # Note : Clé primaire auto-incrémentée, correspond à la colonne SQL 'id_utilisateur'

    nom = models.CharField(max_length=100, db_column="nom", verbose_name=_("Nom"))
    # Nom de famille de l'utilisateur

    prenom = models.CharField(
        max_length=100, db_column="prenom", verbose_name=_("Prénom")
    )
    # Prénom de l'utilisateur

    email = models.EmailField(
        max_length=255, unique=True, db_column="email", verbose_name=_("Adresse email")
    )
    # Email unique utilisé comme identifiant de connexion (USERNAME_FIELD)
    # Contrainte d'unicité garantie au niveau base de données

    password = models.CharField(
        max_length=255, db_column="mot_de_passe", verbose_name=_("Mot de passe hashe")
    )
    # Mot de passe hashe avec l'algorithme Django (PBKDF2)
    # Jamais stocke en clair pour des raisons de securite

    # ============================================
    # GESTION DES RÔLES
    # ============================================
    # IMPORTANT : Le système utilise 4 rôles distincts avec des permissions différentes
    # Cette séparation est critique pour la sécurité et la gestion des accès

    class Role(models.TextChoices):
        """
        Définition des rôles disponibles dans le système.

        Chaque rôle a des permissions spécifiques :
        - ETUDIANT : Consultation uniquement, soumission de justificatifs
        - PROFESSEUR : Saisie des présences/absences, consultation de ses cours
        - SECRETAIRE : Inscriptions, validation justificatifs, encodage absences justifiées
        - ADMIN : Configuration système, gestion utilisateurs (pas d'opérations quotidiennes)
        """

        ETUDIANT = "ETUDIANT", _("Étudiant")
        PROFESSEUR = "PROFESSEUR", _("Professeur")
        SECRETAIRE = "SECRETAIRE", _("Secrétaire")
        ADMIN = "ADMIN", _("Administrateur")

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ETUDIANT,
        db_column="role",
        verbose_name=_("Rôle"),
        db_index=True,  # Index pour accélérer les requêtes filtrées par rôle
    )
    # Rôle de l'utilisateur dans le système
    # Détermine les permissions et l'accès aux fonctionnalités

    # ============================================
    # GESTION DU COMPTE
    # ============================================

    actif = models.BooleanField(
        default=True,
        db_column="actif",
        verbose_name=_("Actif"),
        db_index=True,
        help_text=_("Désactiver un compte le masque sans le supprimer"),
    )
    # Permet de désactiver un compte sans le supprimer (soft delete)
    # Utile pour conserver l'historique tout en bloquant l'accès

    is_staff = models.BooleanField(
        default=False,
        db_column="is_staff",
        verbose_name=_("Staff"),
        help_text=_(
            "Definit si l'utilisateur peut acceder a l'interface d'administration."
        ),
        db_index=True,
    )
    # Deduit automatiquement du role (ADMIN/SECRETAIRE)

    date_creation = models.DateTimeField(
        default=timezone.now,
        db_column="date_creation",
        verbose_name=_("Date de création"),
    )
    # Date de création du compte (automatique)

    must_change_password = models.BooleanField(
        default=False,
        db_column="must_change_password",
        verbose_name=_("Doit changer le mot de passe"),
        help_text=_(
            "Force l'utilisateur à changer son mot de passe à la prochaine connexion"
        ),
        db_index=True,
    )
    # IMPORTANT : Utilisé pour les mots de passe temporaires
    # Lorsqu'un étudiant est créé par le secrétariat, un mot de passe temporaire est généré
    # et ce champ est mis à True. L'étudiant est alors forcé de changer son mot de passe
    # au premier login (middleware RoleMiddleware)

    # ============================================
    # AUTHENTIFICATION À DEUX FACTEURS (TOTP)
    # ============================================

    two_factor_secret = models.CharField(
        max_length=32,
        blank=True,
        default="",
        db_column="two_factor_secret",
        verbose_name=_("Secret TOTP 2FA"),
        help_text=_(
            "Clé secrète Base32 partagée avec l'application d'authentification "
            "(Google Authenticator, Authy, etc.). Vide tant que la 2FA n'est pas activée."
        ),
    )
    # Stocké en clair en DB par contrainte du protocole TOTP. Hashé serait inutile :
    # le serveur doit pouvoir recalculer le code à chaque vérification. Protégez la DB.

    two_factor_enabled = models.BooleanField(
        default=False,
        db_column="two_factor_enabled",
        verbose_name=_("2FA activée"),
        db_index=True,
        help_text=_("Indique si l'utilisateur a activé l'authentification à deux facteurs."),
    )
    # Chaque user décide individuellement d'activer/désactiver la 2FA depuis ses
    # paramètres. Le middleware TwoFactorMiddleware redirige vers verify_2fa
    # tant que la session n'a pas validé le code TOTP.

    # ============================================
    # NIVEAU ACADÉMIQUE (UNIQUEMENT POUR ÉTUDIANTS)
    # ============================================

    niveau = models.IntegerField(
        choices=[(1, "Année 1"), (2, "Année 2"), (3, "Année 3")],
        null=True,
        blank=True,
        db_column="niveau",
        verbose_name=_("Niveau académique"),
        help_text=_(
            "Niveau actuel de l'étudiant (1, 2 ou 3). Uniquement pour les étudiants."
        ),
        db_index=True,
    )
    # Niveau académique de l'étudiant (1, 2 ou 3)
    # Mis à jour automatiquement lors de l'inscription à un niveau complet
    # Utilisé pour :
    # - Filtrer les cours disponibles lors de l'inscription
    # - Vérifier les prérequis (un cours de niveau N ne peut avoir que des prérequis < N)
    # - Valider l'inscription à un niveau supérieur (vérification du niveau précédent)

    # === PROPRIÉTÉS VIRTUELLES (PAS DANS LA BD) ===

    @property
    def is_active(self):
        """Retourne le statut actif (requis par Django)"""
        return self.actif

    @is_active.setter
    def is_active(self, value):
        """Setter pour is_active"""
        self.actif = value

    def _sync_role_flags(self):
        """Synchronise is_staff/is_superuser avec le role."""
        if self.role == self.Role.ADMIN:
            self.is_staff = True
            self.is_superuser = True
        elif self.role == self.Role.SECRETAIRE:
            self.is_staff = True
            self.is_superuser = False
        else:
            self.is_staff = False
            self.is_superuser = False

    def save(self, *args, **kwargs):
        if self.role == self.Role.ETUDIANT and self.niveau is None:
            self.niveau = 1
        self._sync_role_flags()
        update_fields = kwargs.get("update_fields")
        if update_fields:
            kwargs["update_fields"] = list(
                set(update_fields) | {"is_staff", "is_superuser"}
            )
        super().save(*args, **kwargs)

    # === CONFIGURATION DJANGO ===
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nom", "prenom"]

    objects = UserManager()

    # Champ last_login géré par Django (peut être null)
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Dernière connexion"),
        help_text=_("Date et heure de la dernière connexion"),
    )

    class Meta:
        db_table = "utilisateur"
        app_label = "accounts"
        verbose_name = _("Utilisateur")
        verbose_name_plural = _("Utilisateurs")
        ordering = ["nom", "prenom"]
        indexes = [
            models.Index(fields=["nom", "prenom"], name="utilisateur_nom_prenom_idx"),
        ]
        # FIX VERT #16 — Contrainte DB : tout ETUDIANT doit avoir un niveau renseigné.
        # Évite les étudiants sans niveau créés par erreur (bug possible via l'API).
        constraints = [
            models.CheckConstraint(
                condition=(~models.Q(role="ETUDIANT") | models.Q(niveau__isnull=False)),
                name="etudiant_doit_avoir_niveau",
            ),
        ]
        # IMPORTANT: Django ne gère PAS la création/modification de cette table
        managed = True

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.email})"

    def get_full_name(self):
        """Retourne le nom complet de l'utilisateur"""
        return f"{self.prenom} {self.nom}"

    def get_short_name(self):
        """Retourne le prénom de l'utilisateur"""
        return self.prenom

    def has_perm(self, perm, obj=None):
        """Est-ce que l'utilisateur a une permission spécifique?"""
        return self.is_superuser

    def has_module_perms(self, app_label):
        """Est-ce que l'utilisateur a des permissions pour voir l'app?"""
        return self.is_staff or self.is_superuser


class UserSession(models.Model):
    """
    Suivi des sessions actives par utilisateur.

    Permet de limiter le nombre de sessions simultanées (MAX_SESSIONS_PER_USER)
    en supprimant les plus anciennes au-delà du seuil lors de chaque connexion.
    """

    MAX_SESSIONS_PER_USER = 3

    user = models.ForeignKey(
        User,
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

    Généré par lot de 8 lors de l'activation de la 2FA (et lors d'une
    régénération). Le code en clair est affiché à l'utilisateur UNE SEULE
    FOIS — seul son hash est stocké en base. Lorsque l'utilisateur perd son
    téléphone TOTP, il peut saisir un de ces codes sur verify_2fa à la place
    du code TOTP. Un code ne peut servir qu'une fois.
    """

    CODES_PER_BATCH = 8

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="backup_codes",
        verbose_name=_("Utilisateur"),
    )
    code_hash = models.CharField(
        max_length=255,
        verbose_name=_("Hash du code"),
        help_text=_(
            "Hash Django (make_password). Le code en clair n'est jamais stocké."
        ),
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
