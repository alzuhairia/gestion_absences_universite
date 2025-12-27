# apps/accounts/models.py - VERSION CORRIGÉE
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password


class UserManager(BaseUserManager):
    """Manager personnalisé pour le modèle User"""
    
    def create_user(self, email, nom, prenom, password=None, **extra_fields):
        """Crée et sauvegarde un utilisateur normal"""
        if not email:
            raise ValueError(_('L\'adresse email est obligatoire'))
        if not nom:
            raise ValueError(_('Le nom est obligatoire'))
        if not prenom:
            raise ValueError(_('Le prénom est obligatoire'))
        
        email = self.normalize_email(email)
        user = self.model(email=email, nom=nom, prenom=prenom, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, nom, prenom, password=None, **extra_fields):
        """Crée et sauvegarde un superutilisateur (admin)"""
        extra_fields.setdefault('role', 'ADMIN')
        extra_fields.setdefault('actif', True)
        
        return self.create_user(email, nom, prenom, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    Modèle utilisateur 100% compatible avec la table PostgreSQL 'utilisateur'
    CORRECTION: Gestion de is_staff/is_superuser sans colonnes SQL
    """
    
    # === CHAMPS DE LA TABLE SQL (EXACTEMENT COMME TON SCHÉMA) ===
    id_utilisateur = models.AutoField(
        primary_key=True,
        db_column='id_utilisateur',
        verbose_name=_('ID Utilisateur')
    )
    
    nom = models.CharField(
        max_length=100,
        db_column='nom',
        verbose_name=_('Nom')
    )
    
    prenom = models.CharField(
        max_length=100,
        db_column='prenom',
        verbose_name=_('Prénom')
    )
    
    email = models.EmailField(
        max_length=255,
        unique=True,
        db_column='email',
        verbose_name=_('Adresse email')
    )
    
    mot_de_passe = models.CharField(
        max_length=255,
        db_column='mot_de_passe',
        verbose_name=_('Mot de passe hashé')
    )
    
    # Rôles (exactement comme le CHECK SQL)
    class Role(models.TextChoices):
        ETUDIANT = 'ETUDIANT', _('Étudiant')
        PROFESSEUR = 'PROFESSEUR', _('Professeur')
        SECRETAIRE = 'SECRETAIRE', _('Secrétaire')
        ADMIN = 'ADMIN', _('Administrateur')
    
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ETUDIANT,
        db_column='role',
        verbose_name=_('Rôle'),
        db_index=True
    )
    
    actif = models.BooleanField(
        default=True,
        db_column='actif',
        verbose_name=_('Actif'),
        db_index=True,
        help_text=_('Désactiver un compte le masque sans le supprimer')
    )
    
    date_creation = models.DateTimeField(
        default=timezone.now,
        db_column='date_creation',
        verbose_name=_('Date de création')
    )
    
    must_change_password = models.BooleanField(
        default=False,
        db_column='must_change_password',
        verbose_name=_('Doit changer le mot de passe'),
        help_text=_('Force l\'utilisateur à changer son mot de passe à la prochaine connexion'),
        db_index=True
    )
    
    niveau = models.IntegerField(
        choices=[(1, 'Année 1'), (2, 'Année 2'), (3, 'Année 3')],
        null=True,
        blank=True,
        db_column='niveau',
        verbose_name=_('Niveau académique'),
        help_text=_('Niveau actuel de l\'étudiant (1, 2 ou 3). Uniquement pour les étudiants.'),
        db_index=True
    )
    
    # === PROPRIÉTÉS VIRTUELLES (PAS DANS LA BD) ===
    
    @property
    def is_staff(self):
        """Un utilisateur est staff s'il est admin ou secrétaire"""
        return self.role in [self.Role.ADMIN, self.Role.SECRETAIRE]
    
    @is_staff.setter
    def is_staff(self, value):
        """Setter pour compatibilité Django (ignore la valeur)"""
        pass
    
    @property
    def is_superuser(self):
        """Un superuser est un admin"""
        return self.role == self.Role.ADMIN
    
    @is_superuser.setter
    def is_superuser(self, value):
        """Setter pour compatibilité Django (ignore la valeur)"""
        pass
    
    @property
    def is_active(self):
        """Retourne le statut actif (requis par Django)"""
        return self.actif
    
    @is_active.setter
    def is_active(self, value):
        """Setter pour is_active"""
        self.actif = value
    
    # === GESTION DU MOT DE PASSE ===
    
    @property
    def password(self):
        """Propriété pour compatibilité Django"""
        return self.mot_de_passe
    
    @password.setter
    def password(self, raw_password):
        """Setter qui hash le mot de passe"""
        self.set_password(raw_password)
    
    def set_password(self, raw_password):
        """Hash le mot de passe avec l'algorithme Django"""
        if raw_password:
            self.mot_de_passe = make_password(raw_password)
    
    def check_password(self, raw_password):
        """Vérifie le mot de passe contre le hash Django"""
        return check_password(raw_password, self.mot_de_passe)
    
    # === CONFIGURATION DJANGO ===
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nom', 'prenom']
    
    objects = UserManager()
    
    # Champ last_login géré par Django (peut être null)
    last_login = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_('Dernière connexion'),
        help_text=_('Date et heure de la dernière connexion')
    )
    
    class Meta:
        db_table = 'utilisateur'
        app_label = 'accounts'
        verbose_name = _('Utilisateur')
        verbose_name_plural = _('Utilisateurs')
        ordering = ['nom', 'prenom']
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
    
    
