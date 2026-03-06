"""
Signals Django pour la gestion automatique des absences.

IMPORTANT POUR LA SOUTENANCE :
Les signals permettent d'automatiser certaines actions lors de la création/modification
d'objets. Ici, le signal garantit que l'éligibilité à l'examen est toujours à jour.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Absence
from .services import recalculer_eligibilite


def _schedule_eligibility_recalc(inscription_pk):
    """Defer eligibility recalculation to after the current transaction commits."""

    def _recalcul():
        from apps.enrollments.models import Inscription

        try:
            inscription = Inscription.objects.get(pk=inscription_pk)
        except Inscription.DoesNotExist:
            return
        recalculer_eligibilite(inscription)

    transaction.on_commit(_recalcul)


@receiver(post_save, sender=Absence)
def absence_post_save(sender, instance, **kwargs):
    """
    Signal déclenché après chaque sauvegarde d'une Absence.

    Utilise transaction.on_commit() pour différer le recalcul après la fin
    de la transaction en cours, évitant les écritures DB imbriquées et
    garantissant que toutes les données sont cohérentes avant le recalcul.
    """
    _schedule_eligibility_recalc(instance.id_inscription_id)


@receiver(post_delete, sender=Absence)
def absence_post_delete(sender, instance, **kwargs):
    """
    Signal déclenché après la suppression d'une Absence.

    Recalcule l'éligibilité car la suppression d'une absence (ex: professeur
    corrige un étudiant marqué absent par erreur) doit mettre à jour le
    statut eligible_examen.
    """
    _schedule_eligibility_recalc(instance.id_inscription_id)
