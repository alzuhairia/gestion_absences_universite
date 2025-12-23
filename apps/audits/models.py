from django.db import models
from django.conf import settings

class LogAudit(models.Model):
    # Correction ici : on utilise id_log comme dans ta base PostgreSQL
    id_log = models.AutoField(primary_key=True, db_column='id_log')
    
    id_utilisateur = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        models.DO_NOTHING, 
        db_column='id_utilisateur',
        verbose_name="Utilisateur"
    )
    action = models.TextField(verbose_name="Action effectuée")
    date_action = models.DateTimeField(
        auto_now_add=True, 
        db_column='date_action',
        verbose_name="Date et heure"
    )
    adresse_ip = models.GenericIPAddressField(
        db_column='adresse_ip',
        verbose_name="Adresse IP"
    )

    class Meta:
        managed = True
        db_table = 'log_audit'
        app_label = 'audits'
        verbose_name = "Journal d'audit"
        verbose_name_plural = "Journaux d'audit"

    def __str__(self):
        return f"{self.date_action} - {self.id_utilisateur} : {self.action[:50]}"
