from django.db import models
from django.conf import settings


class Notification(models.Model):
    """
    Modèle représentant une notification envoyée à un utilisateur.
    """
    TYPE_CHOICES = [
        ('INTERNE', 'Interne'),
        ('ALERTE', 'Alerte'),
        ('INFO', 'Information'),
    ]
    
    id_notification = models.AutoField(primary_key=True, db_column='id_notification')
    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.CASCADE,  # Supprimer les notifications si l'utilisateur est supprimé
        db_column='id_utilisateur',
        verbose_name="Utilisateur",
        related_name='notifications'
    )
    message = models.TextField(
        db_column='message',
        verbose_name="Message",
        help_text="Contenu de la notification"
    )
    type = models.CharField(
        max_length=20, 
        choices=TYPE_CHOICES,
        blank=True, 
        null=True, 
        db_column='type',
        verbose_name="Type",
        db_index=True
    )
    lue = models.BooleanField(
        default=False, 
        db_column='lue',
        verbose_name="Lu",
        db_index=True,
        help_text="Indique si la notification a été lue"
    )
    date_envoi = models.DateTimeField(
        auto_now_add=True, 
        db_column='date_envoi',
        verbose_name="Date d'envoi",
        db_index=True
    )

    class Meta:
        managed = True
        db_table = 'notification'
        app_label = 'notifications'
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-date_envoi', '-id_notification']
        indexes = [
            models.Index(fields=['id_utilisateur', 'lue', 'date_envoi']),
            models.Index(fields=['type', 'date_envoi']),
        ]

    def __str__(self):
        return f"Notification pour {self.id_utilisateur} - {self.date_envoi}"
