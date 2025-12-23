from django.db import models
from django.conf import settings

class Message(models.Model):
    id_message = models.AutoField(primary_key=True)
    expediteur = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='expediteur')
    destinataire = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='destinataire', related_name='message_destinataire_set')
    objet = models.CharField(max_length=200, default="Nouveau message", verbose_name="Objet")
    contenu = models.TextField(verbose_name="Message")
    date_envoi = models.DateTimeField(auto_now_add=True, verbose_name="Date d'envoi")
    lu = models.BooleanField(default=False)

    class Meta:
        managed = True
        db_table = 'message'
        app_label = 'messaging'
