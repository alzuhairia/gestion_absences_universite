"""
Modèles utilisateur : UserManager et User (modèle custom AUTH_USER_MODEL).
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
    4 rôles : ETUDIANT, PROFESSEUR, SECRETAIRE, ADMIN.
    Identifiant : email (pas username).
    """

    class Role(models.TextChoices):
        ETUDIANT = "ETUDIANT", _("Étudiant")
        PROFESSEUR = "PROFESSEUR", _("Professeur")
        SECRETAIRE = "SECRETAIRE", _("Secrétaire")
        ADMIN = "ADMIN", _("Administrateur")

    id_utilisateur = models.AutoField(
        primary_key=True, db_column="id_utilisateur", verbose_name=_("ID Utilisateur")
    )
    nom = models.CharField(max_length=100, db_column="nom", verbose_name=_("Nom"))
    prenom = models.CharField(max_length=100, db_column="prenom", verbose_name=_("Prénom"))
    email = models.EmailField(
        max_length=255, unique=True, db_column="email", verbose_name=_("Adresse email")
    )
    password = models.CharField(
        max_length=255, db_column="mot_de_passe", verbose_name=_("Mot de passe hashe")
    )

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ETUDIANT,
        db_column="role",
        verbose_name=_("Rôle"),
        db_index=True,
    )

    actif = models.BooleanField(
        default=True,
        db_column="actif",
        verbose_name=_("Actif"),
        db_index=True,
        help_text=_("Désactiver un compte le masque sans le supprimer"),
    )
    is_staff = models.BooleanField(
        default=False,
        db_column="is_staff",
        verbose_name=_("Staff"),
        help_text=_("Definit si l'utilisateur peut acceder a l'interface d'administration."),
        db_index=True,
    )
    date_creation = models.DateTimeField(
        default=timezone.now,
        db_column="date_creation",
        verbose_name=_("Date de création"),
    )
    must_change_password = models.BooleanField(
        default=False,
        db_column="must_change_password",
        verbose_name=_("Doit changer le mot de passe"),
        help_text=_("Force l'utilisateur à changer son mot de passe à la prochaine connexion"),
        db_index=True,
    )

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
    # Stocké en clair par contrainte du protocole TOTP — le serveur doit recalculer le code.
    two_factor_enabled = models.BooleanField(
        default=False,
        db_column="two_factor_enabled",
        verbose_name=_("2FA activée"),
        db_index=True,
        help_text=_("Indique si l'utilisateur a activé l'authentification à deux facteurs."),
    )

    niveau = models.IntegerField(
        choices=[(1, "Année 1"), (2, "Année 2"), (3, "Année 3")],
        null=True,
        blank=True,
        db_column="niveau",
        verbose_name=_("Niveau académique"),
        help_text=_("Niveau actuel de l'étudiant (1, 2 ou 3). Uniquement pour les étudiants."),
        db_index=True,
    )

    @property
    def is_active(self):  # type: ignore[override]
        """Retourne le statut actif (requis par Django)"""
        return self.actif

    @is_active.setter
    def is_active(self, value):  # type: ignore[override]
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

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["nom", "prenom"]

    objects = UserManager()

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
        constraints = [
            models.CheckConstraint(
                condition=(~models.Q(role="ETUDIANT") | models.Q(niveau__isnull=False)),
                name="etudiant_doit_avoir_niveau",
            ),
        ]
        managed = True

    def __str__(self):
        return f"{self.prenom} {self.nom} ({self.email})"

    def get_full_name(self):
        return f"{self.prenom} {self.nom}"

    def get_short_name(self):
        return self.prenom

    def has_perm(self, perm, obj=None):
        return self.is_superuser

    def has_module_perms(self, app_label):
        return self.is_staff or self.is_superuser
