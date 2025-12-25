from django.db import models
from django.conf import settings


class LogAudit(models.Model):
    """
    Modèle représentant un journal d'audit pour tracer toutes les actions critiques du système.
    Les logs sont en lecture seule et ne peuvent pas être supprimés.
    """
    NIVEAU_CHOICES = [
        ('INFO', 'Information'),
        ('WARNING', 'Avertissement'),
        ('CRITIQUE', 'Critique'),
    ]
    
    OBJET_TYPE_CHOICES = [
        ('USER', 'Utilisateur'),
        ('COURS', 'Cours'),
        ('FACULTE', 'Faculté'),
        ('DEPARTEMENT', 'Département'),
        ('INSCRIPTION', 'Inscription'),
        ('ABSENCE', 'Absence'),
        ('JUSTIFICATION', 'Justification'),
        ('SYSTEM', 'Système'),
        ('AUTRE', 'Autre'),
    ]
    
    id_log = models.AutoField(primary_key=True, db_column='id_log')
    
    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.PROTECT,  # Empêche la suppression d'un utilisateur avec des logs d'audit
        db_column='id_utilisateur',
        verbose_name="Utilisateur",
        related_name='audit_logs'
    )
    action = models.TextField(
        verbose_name="Action effectuée",
        help_text="Description détaillée de l'action"
    )
    date_action = models.DateTimeField(
        auto_now_add=True, 
        db_column='date_action',
        verbose_name="Date et heure",
        db_index=True
    )
    adresse_ip = models.GenericIPAddressField(
        db_column='adresse_ip',
        verbose_name="Adresse IP",
        help_text="Adresse IP de l'utilisateur ayant effectué l'action"
    )
    niveau = models.CharField(
        max_length=20,
        choices=NIVEAU_CHOICES,
        default='INFO',
        verbose_name="Niveau",
        db_index=True,
        help_text="Niveau de criticité de l'action"
    )
    objet_type = models.CharField(
        max_length=50,
        choices=OBJET_TYPE_CHOICES,
        null=True,
        blank=True,
        verbose_name="Type d'objet",
        db_index=True,
        help_text="Type d'objet affecté par l'action"
    )
    objet_id = models.IntegerField(
        null=True,
        blank=True,
        verbose_name="ID de l'objet",
        db_index=True,
        help_text="Identifiant de l'objet affecté"
    )

    class Meta:
        managed = True
        db_table = 'log_audit'
        app_label = 'audits'
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"
        ordering = ['-date_action']
        indexes = [
            models.Index(fields=['date_action', 'niveau']),
            models.Index(fields=['objet_type', 'objet_id']),
            models.Index(fields=['id_utilisateur', 'date_action']),
            models.Index(fields=['niveau', 'date_action']),
        ]

    def __str__(self):
        return f"{self.date_action} - {self.id_utilisateur} : {self.action[:50]}"
