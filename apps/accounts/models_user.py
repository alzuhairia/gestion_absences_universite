"""
Modèle utilisateur personnalisé et manager pour le système universitaire de gestion des absences UniAbsences.

Ce module définit le modèle d'authentification central utilisé comme
AUTH_USER_MODEL de Django. Il remplace l'User intégré de Django basé sur
le nom d'utilisateur par un modèle basé sur l'email qui porte un rôle
universitaire (ETUDIANT, PROFESSEUR, SECRETAIRE, ADMIN) et supporte
l'authentification à deux facteurs basée sur TOTP.

Responsabilités :
  - Définir ``UserManager`` avec les méthodes fabriques ``create_user`` et ``create_superuser``.
  - Définir le modèle ``User`` avec l'email comme identifiant unique (pas de username).
  - Synchroniser automatiquement ``is_staff`` / ``is_superuser`` avec le champ rôle.
  - Imposer une contrainte au niveau base de données : chaque ETUDIANT doit avoir une valeur ``niveau``.
  - Stocker le secret TOTP et le drapeau 2FA-activée directement sur l'enregistrement utilisateur.

Fait partie du système de comptes UniAbsences.
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
    """
    Manager personnalisé pour le modèle ``User``.

    Fournit ``create_user`` pour les comptes réguliers et ``create_superuser``
    pour les comptes administratifs, tous deux utilisant l'email comme
    identifiant principal.
    """

    def create_user(self, email, nom, prenom, password=None, **extra_fields):
        """
        Crée et persiste un compte utilisateur régulier.

        Le rôle par défaut est ETUDIANT lorsqu'il n'est pas fourni. Les
        étudiants reçoivent ``niveau=1`` automatiquement si aucun niveau
        n'est spécifié. ``set_password`` de Django est utilisé afin que le
        mot de passe soit toujours stocké comme hash sécurisé. Les drapeaux
        de rôle (``is_staff``, ``is_superuser``) sont synchronisés via
        ``_sync_role_flags`` avant la première sauvegarde.

        Parameters:
            email (str): Identifiant principal — doit être unique et non vide.
            nom (str): Nom de famille de l'utilisateur.
            prenom (str): Prénom de l'utilisateur.
            password (str | None): Mot de passe en texte clair ; ``None`` crée
                un mot de passe inutilisable (``set_unusable_password``).
            **extra_fields: Toutes valeurs additionnelles des champs ``User``,
                par ex. ``role``, ``niveau``, ``actif``.

        Returns:
            User: L'instance utilisateur nouvellement créée et sauvegardée.

        Raises:
            ValueError: Si ``email``, ``nom`` ou ``prenom`` est vide.
        """
        if not email:
            raise ValueError(_("L'adresse email est obligatoire"))
        if not nom:
            raise ValueError(_("Le nom est obligatoire"))
        if not prenom:
            raise ValueError(_("Le prénom est obligatoire"))

        email = self.normalize_email(email)
        # Rôle par défaut ETUDIANT ; les étudiants doivent toujours avoir un niveau.
        role = extra_fields.setdefault("role", self.model.Role.ETUDIANT)
        if role == self.model.Role.ETUDIANT and extra_fields.get("niveau") is None:
            extra_fields["niveau"] = 1
        user = self.model(email=email, nom=nom, prenom=prenom, **extra_fields)
        user.set_password(password)
        # S'assurer que is_staff / is_superuser correspondent au rôle avant écriture en BDD.
        user._sync_role_flags()
        user.save(using=self._db)
        return user

    def create_superuser(self, email, nom, prenom, password=None, **extra_fields):
        """
        Crée et persiste un compte superuser administratif.

        Force ``role=ADMIN``, ``is_staff=True`` et ``is_superuser=True``.
        Lève ``ValueError`` si l'un de ces drapeaux est explicitement défini
        à ``False`` par l'appelant, empêchant toute mauvaise configuration
        accidentelle.

        Parameters:
            email (str): Adresse email de l'admin.
            nom (str): Nom de famille.
            prenom (str): Prénom.
            password (str | None): Mot de passe en texte clair.
            **extra_fields: Valeurs additionnelles des champs du modèle.

        Returns:
            User: Le nouvel utilisateur admin créé.

        Raises:
            ValueError: Si ``is_staff`` ou ``is_superuser`` est défini à ``False``.
        """
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
    Modèle utilisateur central pour UniAbsences.

    Utilise l'email comme identifiant unique de connexion plutôt qu'un
    username. Chaque utilisateur appartient à l'un des quatre rôles
    (ETUDIANT, PROFESSEUR, SECRETAIRE, ADMIN) qui contrôle les niveaux
    d'accès à travers l'application. Le modèle stocke aussi le secret
    partagé TOTP et le drapeau 2FA-activée afin que l'état d'authentification
    soit toujours colocalisé avec l'enregistrement utilisateur.
    """

    class Role(models.TextChoices):
        """Énumération de tous les rôles utilisateur dans le système universitaire."""

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
    # AUTHENTIFICATION À DEUX FACTEURS (TOTP / RFC 6238)
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
    # Le secret TOTP est intentionnellement stocké en clair. Le protocole TOTP
    # (RFC 6238) impose au serveur de recalculer l'OTP courant à partir du
    # secret partagé à chaque vérification, il ne peut donc pas être hashé.
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
        """
        Propriété de compatibilité Django — mappée sur la colonne BDD ``actif``.

        Le framework d'authentification de Django vérifie ``is_active`` pour
        décider si un utilisateur peut se connecter. Ce projet stocke le
        même concept dans ``actif`` (nom français correspondant au schéma
        BDD universitaire), donc cette propriété fait le pont entre les
        deux noms.
        """
        return self.actif

    @is_active.setter
    def is_active(self, value):  # type: ignore[override]
        """Setter pour que le propre code Django (par ex. admin) puisse écrire ``is_active``."""
        self.actif = value

    def _sync_role_flags(self):
        """
        Maintient ``is_staff`` et ``is_superuser`` cohérents avec le champ ``role``.

        Résumé des règles :
          - ADMIN      → is_staff=True,  is_superuser=True  (accès Django admin complet)
          - SECRETAIRE → is_staff=True,  is_superuser=False (Django admin lecture seule)
          - Tous autres → is_staff=False, is_superuser=False

        Cette méthode est appelée à la fois par ``UserManager.create_user``
        et ``save`` afin que les drapeaux soient toujours corrects quel que
        soit le moyen de modification de l'objet.
        """
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
        """
        Surcharge ``save`` pour appliquer les invariants métier avant écriture en BDD.

        - Les étudiants sans ``niveau`` explicite reçoivent l'année 1 par défaut.
        - ``_sync_role_flags`` est appelé pour que ``is_staff``/``is_superuser``
          reflètent toujours le ``role`` courant.
        - Lorsqu'une liste partielle ``update_fields`` est fournie, ``is_staff``
          et ``is_superuser`` sont ajoutés automatiquement pour empêcher
          des valeurs obsolètes de subsister en base après un changement de rôle.

        Effets de bord : écriture dans la table ``utilisateur``.
        """
        if self.role == self.Role.ETUDIANT and self.niveau is None:
            self.niveau = 1
        self._sync_role_flags()
        # Si un appelant passe update_fields, toujours inclure les drapeaux de permission
        # pour qu'ils restent synchronisés même quand seul 'role' est mis à jour.
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
        """Métadonnées Django : table ``utilisateur``, index nom+prénom et contrainte (étudiant ⇒ niveau)."""

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
        """Retourne une représentation lisible : 'Prénom Nom (email)'."""
        return f"{self.prenom} {self.nom} ({self.email})"

    def get_full_name(self):
        """Retourne le nom complet de l'utilisateur dans l'ordre 'Prénom Nom' (convention Django)."""
        return f"{self.prenom} {self.nom}"

    def get_short_name(self):
        """Retourne uniquement le prénom, utilisé par Django dans certains contextes UI."""
        return self.prenom

    def has_perm(self, perm, obj=None):
        """
        Retourne True si l'utilisateur dispose de la permission spécifiée.

        Implémentation simplifiée : seuls les superusers (rôle ADMIN) se voient
        accorder toutes les permissions. Les utilisateurs non admin sont
        soumis aux contrôles au niveau objet définis ailleurs dans l'application.
        """
        return self.is_superuser

    def has_module_perms(self, app_label):
        """
        Retourne True si l'utilisateur a des permissions dans l'app donnée.

        Les membres du staff (rôles SECRETAIRE et ADMIN) peuvent voir les
        modules Django admin ; l'accès complet est limité aux superusers
        (rôle ADMIN).
        """
        return self.is_staff or self.is_superuser
