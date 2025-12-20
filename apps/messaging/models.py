from django.db import models
from django.conf import settings

class Message(models.Model):
    id_message = models.AutoField(primary_key=True)
    expediteur = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='expediteur')
    destinataire = models.ForeignKey(settings.AUTH_USER_MODEL, models.DO_NOTHING, db_column='destinataire', related_name='message_destinataire_set')
    contenu = models.TextField()
    date_envoi = models.DateTimeField(blank=True, null=True, auto_now_add=True)
    lu = models.BooleanField(default=False)

    class Meta:
        managed = False
        db_table = 'message'
        app_label = 'messaging'