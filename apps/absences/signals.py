from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Absence
from .services import recalculer_eligibilite

@receiver(post_save, sender=Absence)
def absence_post_save(sender, instance, **kwargs):
    # On appelle le service de recalcul
    recalculer_eligibilite(instance.id_inscription)