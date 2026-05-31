"""
Modèle de configuration globale du système pour le tableau de bord UniAbsences.

Définit le modèle singleton ``SystemSettings`` qui stocke les paramètres
globaux ajustables utilisés à travers toute l'application : seuils
d'absence, règles de complexité des mots de passe, paramètres de
présence GPS/QR et politiques de conservation des données RGPD.

Le singleton est appliqué au niveau de la base de données via une
``CheckConstraint`` qui restreint ``id`` à 1, et au niveau applicatif
via la surcharge ``save()`` qui force toujours ``id = 1`` avant la
persistance.

Un cache éphémère Redis/en mémoire (``SYSTEM_SETTINGS_CACHE_TIMEOUT``)
évite un accès à la base à chaque chargement de page ; le cache est
invalidé automatiquement à chaque sauvegarde de l'enregistrement.

Fait partie du système de tableau de bord UniAbsences.
"""

from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _

# Clé de cache utilisée pour stocker l'instance singleton de SystemSettings.
SYSTEM_SETTINGS_CACHE_KEY = "system_settings_singleton"

# Durée (en secondes) pendant laquelle l'objet de paramètres en cache est considéré comme frais.
SYSTEM_SETTINGS_CACHE_TIMEOUT = 300  # 5 minutes


class SystemSettings(models.Model):
    """
    Modèle singleton stockant la configuration globale du système.

    Une seule ligne (id=1) ne doit jamais exister.  Toutes les lectures
    doivent passer par ``get_settings()`` afin que la couche de cache
    soit respectée.  Toutes les écritures doivent utiliser ``save()``
    (ou le formulaire d'administration) afin que le cache soit invalidé
    et que la contrainte de singleton soit maintenue.

    Attributes
    ----------
    default_absence_threshold : int
        Seuil de pourcentage d'absence par défaut appliqué aux nouveaux cours.
    block_type : str
        Comportement lorsque le seuil d'absence est dépassé (alerte
        uniquement vs blocage d'examen).
    password_min_length : int
        Nombre minimum de caractères pour les mots de passe utilisateur.
    password_require_* : bool
        Exigences individuelles de classes de caractères pour les mots de passe.
    mfa_enabled_globally : bool
        Indique si l'authentification à deux facteurs est obligatoire
        pour tous les utilisateurs.
    gps_latitude / gps_longitude : float or None
        Coordonnées GPS de l'établissement utilisées pour valider les
        emplacements de scan QR.
    gps_radius_meters : int
        Rayon d'acceptation (mètres) autour du point GPS de l'établissement.
    qr_token_duration_seconds : int
        Durée de vie de chaque jeton QR de présence tournant.
    data_retention_days : int
        Nombre de jours pendant lesquels les données personnelles sont
        conservées (conformité RGPD).
    last_modified : datetime
        Horodatage auto-mis à jour de la dernière sauvegarde.
    modified_by : User or None
        Clé étrangère vers l'admin qui a sauvegardé les paramètres en dernier.
    """

    class BlockType(models.TextChoices):
        """
        Définit le comportement du système lorsque le taux d'absence
        d'un étudiant dépasse le seuil configuré.

        ALERT_ONLY : enregistre le dépassement mais autorise l'étudiant à passer les examens.
        EXAM_BLOCK : empêche l'étudiant de s'inscrire aux examens officiels.
        """

        ALERT_ONLY = "ALERT_ONLY", _("Alerte uniquement")
        EXAM_BLOCK = "EXAM_BLOCK", _("Blocage examen officiel")

    # Clé primaire du singleton
    id = models.AutoField(primary_key=True)

    # Règles académiques
    default_absence_threshold = models.IntegerField(
        default=40,
        verbose_name="Seuil d'absence par défaut (%)",
        help_text="Seuil par défaut appliqué aux nouveaux cours",
    )

    block_type = models.CharField(
        max_length=20,
        choices=BlockType.choices,
        default=BlockType.EXAM_BLOCK,
        verbose_name="Type de blocage",
        help_text="Comportement lorsque le seuil est dépassé",
    )

    # Paramètres de sécurité
    password_min_length = models.IntegerField(
        default=8, verbose_name="Longueur minimale du mot de passe"
    )
    password_require_uppercase = models.BooleanField(
        default=True, verbose_name="Exiger majuscules"
    )
    password_require_lowercase = models.BooleanField(
        default=True, verbose_name="Exiger minuscules"
    )
    password_require_numbers = models.BooleanField(
        default=True, verbose_name="Exiger chiffres"
    )
    password_require_special = models.BooleanField(
        default=False, verbose_name="Exiger caractères spéciaux"
    )

    mfa_enabled_globally = models.BooleanField(
        default=False, verbose_name="Authentification à deux facteurs (globale)"
    )

    # Présence GPS / QR
    gps_latitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Latitude de l'établissement",
        help_text="Latitude GPS de l'établissement (ex: 36.7525)",
    )
    gps_longitude = models.FloatField(
        null=True,
        blank=True,
        verbose_name="Longitude de l'établissement",
        help_text="Longitude GPS de l'établissement (ex: 3.0420)",
    )
    gps_radius_meters = models.PositiveIntegerField(
        default=100,
        verbose_name="Rayon de tolérance GPS (mètres)",
        help_text="Distance maximale acceptée entre l'étudiant et l'établissement",
    )
    qr_token_duration_seconds = models.PositiveIntegerField(
        default=60,
        verbose_name="Durée de validité du QR (secondes)",
        help_text="Le QR se régénère automatiquement après cette durée (défaut : 60s)",
    )

    # Conformité RGPD
    data_retention_days = models.IntegerField(
        default=365,
        verbose_name="Rétention des données (jours)",
        help_text="Durée de conservation des données personnelles",
    )

    # Métadonnées
    last_modified = models.DateTimeField(
        auto_now=True, verbose_name="Dernière modification"
    )
    modified_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="modified_settings",
        verbose_name="Modifié par",
    )

    class Meta:
        """Métadonnées Django : table ``system_settings``, singleton imposé par contrainte ``pk=1``."""

        db_table = "system_settings"
        app_label = "dashboard"
        verbose_name = "Paramètres système"
        verbose_name_plural = "Paramètres système"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name="system_settings_singleton_id_1",
            ),
            models.CheckConstraint(
                condition=models.Q(default_absence_threshold__gte=0)
                & models.Q(default_absence_threshold__lte=100),
                name="system_settings_default_threshold_range",
            ),
            models.CheckConstraint(
                condition=models.Q(password_min_length__gte=4)
                & models.Q(password_min_length__lte=128),
                name="system_settings_password_min_length_range",
            ),
            models.CheckConstraint(
                condition=models.Q(data_retention_days__gte=1)
                & models.Q(data_retention_days__lte=3650),
                name="system_settings_data_retention_days_range",
            ),
        ]

    def __str__(self):
        """Retourne le nom lisible par un humain de cet enregistrement singleton."""
        return "Paramètres système"

    @classmethod
    def get_settings(cls):
        """
        Récupère l'instance singleton ``SystemSettings``.

        Tente d'abord de lire depuis le cache en mémoire/Redis.  En cas
        d'absence du cache, l'enregistrement est récupéré (ou créé)
        depuis la base de données puis mis en cache pour
        ``SYSTEM_SETTINGS_CACHE_TIMEOUT`` secondes.

        Returns
        -------
        SystemSettings
            L'enregistrement unique des paramètres système (id=1),
            garanti d'exister après cet appel.
        """
        obj = cache.get(SYSTEM_SETTINGS_CACHE_KEY)
        if obj is None:
            # Crée le singleton avec des valeurs par défaut sûres s'il n'existe pas encore.
            obj, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    "default_absence_threshold": 40,
                    "block_type": cls.BlockType.EXAM_BLOCK,
                },
            )
            cache.set(SYSTEM_SETTINGS_CACHE_KEY, obj, SYSTEM_SETTINGS_CACHE_TIMEOUT)
        return obj

    def save(self, *args, **kwargs):
        """
        Persiste l'enregistrement singleton des paramètres et invalide le cache.

        Force ``id = 1`` avant la sauvegarde pour appliquer le patron
        singleton, puis exécute ``full_clean()`` afin que tous les
        validateurs de champs soient appliqués même lors d'une
        sauvegarde programmatique (et non via un formulaire).  Enfin,
        supprime l'entrée du cache afin que le prochain appel à
        ``get_settings()`` lise la valeur fraîche.

        Parameters
        ----------
        *args, **kwargs
            Transmis à ``Model.save()``.
        """
        # Applique le singleton : écrit toujours sur la ligne id=1.
        self.id = 1
        self.full_clean()
        super().save(*args, **kwargs)
        # Invalide l'instance en cache afin que des valeurs périmées ne soient jamais servies.
        cache.delete(SYSTEM_SETTINGS_CACHE_KEY)

    def clean(self):
        """
        Valide les intervalles de champs avant la sauvegarde.

        Raises
        ------
        django.core.exceptions.ValidationError
            Si ``default_absence_threshold`` est hors de [0, 100],
            ``password_min_length`` est hors de [4, 128], ou
            ``data_retention_days`` est hors de [1, 3650].
        """
        from django.core.exceptions import ValidationError

        if self.default_absence_threshold < 0 or self.default_absence_threshold > 100:
            raise ValidationError(
                {"default_absence_threshold": "Le seuil doit être entre 0 et 100%."}
            )

        if self.password_min_length < 4 or self.password_min_length > 128:
            raise ValidationError(
                {
                    "password_min_length": "La longueur minimale du mot de passe doit être entre 4 et 128 caractères."
                }
            )

        if self.data_retention_days < 1 or self.data_retention_days > 3650:
            raise ValidationError(
                {
                    "data_retention_days": "La rétention des données doit être entre 1 et 3650 jours."
                }
            )
