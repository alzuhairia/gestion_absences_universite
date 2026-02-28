from django.core.cache import cache
from django.db import models
from django.utils.translation import gettext_lazy as _

SYSTEM_SETTINGS_CACHE_KEY = 'system_settings_singleton'
SYSTEM_SETTINGS_CACHE_TIMEOUT = 300  # 5 minutes


class SystemSettings(models.Model):
    """
    Global system settings managed by administrators.
    Only one instance should exist (singleton pattern).
    """
    
    class BlockType(models.TextChoices):
        ALERT_ONLY = 'ALERT_ONLY', _('Alerte uniquement')
        EXAM_BLOCK = 'EXAM_BLOCK', _('Blocage examen officiel')
    
    # Singleton primary key
    id = models.AutoField(primary_key=True)
    
    # Academic Rules
    default_absence_threshold = models.IntegerField(
        default=40,
        verbose_name="Seuil d'absence par défaut (%)",
        help_text="Seuil par défaut appliqué aux nouveaux cours"
    )
    
    block_type = models.CharField(
        max_length=20,
        choices=BlockType.choices,
        default=BlockType.EXAM_BLOCK,
        verbose_name="Type de blocage",
        help_text="Comportement lorsque le seuil est dépassé"
    )
    
    # Security Settings
    password_min_length = models.IntegerField(
        default=8,
        verbose_name="Longueur minimale du mot de passe"
    )
    password_require_uppercase = models.BooleanField(
        default=True,
        verbose_name="Exiger majuscules"
    )
    password_require_lowercase = models.BooleanField(
        default=True,
        verbose_name="Exiger minuscules"
    )
    password_require_numbers = models.BooleanField(
        default=True,
        verbose_name="Exiger chiffres"
    )
    password_require_special = models.BooleanField(
        default=False,
        verbose_name="Exiger caractères spéciaux"
    )
    
    mfa_enabled_globally = models.BooleanField(
        default=False,
        verbose_name="Authentification à deux facteurs (globale)"
    )
    
    # GDPR Compliance
    data_retention_days = models.IntegerField(
        default=365,
        verbose_name="Rétention des données (jours)",
        help_text="Durée de conservation des données personnelles"
    )
    
    # Metadata
    last_modified = models.DateTimeField(
        auto_now=True,
        verbose_name="Dernière modification"
    )
    modified_by = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modified_settings',
        verbose_name="Modifié par"
    )
    
    class Meta:
        db_table = 'system_settings'
        app_label = 'dashboard'
        verbose_name = "Paramètres système"
        verbose_name_plural = "Paramètres système"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(id=1),
                name='system_settings_singleton_id_1',
            ),
            models.CheckConstraint(
                condition=
                    models.Q(default_absence_threshold__gte=0)
                    & models.Q(default_absence_threshold__lte=100),
                name='system_settings_default_threshold_range',
            ),
            models.CheckConstraint(
                condition=
                    models.Q(password_min_length__gte=4)
                    & models.Q(password_min_length__lte=128),
                name='system_settings_password_min_length_range',
            ),
            models.CheckConstraint(
                condition=
                    models.Q(data_retention_days__gte=1)
                    & models.Q(data_retention_days__lte=3650),
                name='system_settings_data_retention_days_range',
            ),
        ]
    
    def __str__(self):
        return "Paramètres système"
    
    @classmethod
    def get_settings(cls):
        """Récupère le singleton depuis le cache, ou depuis la DB en fallback."""
        obj = cache.get(SYSTEM_SETTINGS_CACHE_KEY)
        if obj is None:
            obj, _ = cls.objects.get_or_create(
                id=1,
                defaults={
                    'default_absence_threshold': 40,
                    'block_type': cls.BlockType.EXAM_BLOCK,
                }
            )
            cache.set(SYSTEM_SETTINGS_CACHE_KEY, obj, SYSTEM_SETTINGS_CACHE_TIMEOUT)
        return obj

    def save(self, *args, **kwargs):
        """Singleton + invalidation du cache à chaque modification admin."""
        self.id = 1
        self.full_clean()
        super().save(*args, **kwargs)
        cache.delete(SYSTEM_SETTINGS_CACHE_KEY)
    
    def clean(self):
        """Validation des paramètres"""
        from django.core.exceptions import ValidationError
        
        if self.default_absence_threshold < 0 or self.default_absence_threshold > 100:
            raise ValidationError({
                'default_absence_threshold': 'Le seuil doit être entre 0 et 100%.'
            })
        
        if self.password_min_length < 4 or self.password_min_length > 128:
            raise ValidationError({
                'password_min_length': 'La longueur minimale du mot de passe doit être entre 4 et 128 caractères.'
            })
        
        if self.data_retention_days < 1 or self.data_retention_days > 3650:
            raise ValidationError({
                'data_retention_days': 'La rétention des données doit être entre 1 et 3650 jours.'
            })


