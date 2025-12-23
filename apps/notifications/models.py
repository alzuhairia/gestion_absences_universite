from django.db import models
from django.conf import settings

class Notification(models.Model):
    id_notification = models.AutoField(primary_key=True, db_column='id_notification')
    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.DO_NOTHING, 
        db_column='id_utilisateur'
    )
    message = models.TextField(db_column='message')
    type = models.CharField(max_length=20, blank=True, null=True, db_column='type')
    
    # ATTENTION : vérifie si c'est 'lu' ou 'lue' dans ta base !
    lue = models.BooleanField(default=False, db_column='lue') 
    
    date_envoi = models.DateTimeField(
        auto_now_add=True, 
        db_column='date_envoi'
    )

    class Meta:
        managed = True
        db_table = 'notification'
        app_label = 'notifications'
