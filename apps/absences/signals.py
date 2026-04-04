"""
FICHIER : apps/absences/signals.py
RESPONSABILITE : Signaux Django pour recalcul automatique de l'eligibilite
FONCTIONNALITES PRINCIPALES :
  - post_save sur Absence : recalcule eligibilite apres chaque sauvegarde
  - post_delete sur Absence : recalcule eligibilite apres suppression
  - Utilise transaction.on_commit() pour eviter les ecritures imbriquees
DEPENDANCES CLES : absences.services.recalculer_eligibilite
"""

import logging

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Absence
from .services import recalculer_eligibilite

logger = logging.getLogger("django")

CACHE_KEY_AT_RISK = "admin_dashboard:at_risk_count"


def _schedule_eligibility_recalc(inscription_pk):
    """Defer eligibility recalculation to after the current transaction commits."""

    def _recalcul():
        from apps.enrollments.models import Inscription

        try:
            inscription = Inscription.objects.get(pk=inscription_pk)
        except Inscription.DoesNotExist:
            return
        try:
            recalculer_eligibilite(inscription)
        except Exception:
            logger.exception(
                "Failed to recalculate eligibility for inscription %s",
                inscription_pk,
            )

    transaction.on_commit(_recalcul)


@receiver(post_save, sender=Absence)
def absence_post_save(sender, instance, **kwargs):
    """
    Signal déclenché après chaque sauvegarde d'une Absence.

    Utilise transaction.on_commit() pour différer le recalcul après la fin
    de la transaction en cours, évitant les écritures DB imbriquées et
    garantissant que toutes les données sont cohérentes avant le recalcul.
    """
    if instance.id_inscription_id:
        _schedule_eligibility_recalc(instance.id_inscription_id)
        cache.delete(CACHE_KEY_AT_RISK)


@receiver(post_delete, sender=Absence)
def absence_post_delete(sender, instance, **kwargs):
    """
    Signal déclenché après la suppression d'une Absence.

    Recalcule l'éligibilité car la suppression d'une absence (ex: professeur
    corrige un étudiant marqué absent par erreur) doit mettre à jour le
    statut eligible_examen.
    """
    if instance.id_inscription_id:
        _schedule_eligibility_recalc(instance.id_inscription_id)
        cache.delete(CACHE_KEY_AT_RISK)
