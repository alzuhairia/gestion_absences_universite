from django.conf import settings
from django.core.validators import MaxLengthValidator
from django.db import models


class Message(models.Model):
    """
    Modèle représentant un message entre deux utilisateurs.
    """

    id_message = models.AutoField(primary_key=True)
    expediteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,  # Si l'expéditeur est supprimé, le champ devient NULL
        db_column="expediteur",
        verbose_name="Expéditeur",
        related_name="messages_envoyes",
        null=True,
        blank=True,
    )
    destinataire = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        models.SET_NULL,  # Si le destinataire est supprimé, le champ devient NULL
        db_column="destinataire",
        related_name="messages_recus",
        verbose_name="Destinataire",
        null=True,
        blank=True,
    )
    objet = models.CharField(
        max_length=200, default="Nouveau message", verbose_name="Objet", db_index=True
    )
    contenu = models.TextField(verbose_name="Message", validators=[MaxLengthValidator(10000)])
    date_envoi = models.DateTimeField(
        auto_now_add=True, verbose_name="Date d'envoi", db_index=True
    )
    lu = models.BooleanField(
        default=False,
        verbose_name="Lu",
        db_index=True,
        help_text="Indique si le message a été lu",
    )

    class Meta:
        managed = True
        db_table = "message"
        app_label = "messaging"
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        ordering = ["-date_envoi"]
        indexes = [
            models.Index(fields=["destinataire", "lu", "date_envoi"]),
            models.Index(fields=["expediteur", "date_envoi"]),
        ]

    def __str__(self):
        sender = str(self.expediteur) if self.expediteur else "(supprimé)"
        recipient = str(self.destinataire) if self.destinataire else "(supprimé)"
        return f"Message de {sender} à {recipient} - {self.objet}"
