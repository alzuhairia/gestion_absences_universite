"""
Signaux Django pour le recalcul automatique de l'éligibilité dans l'app absences.

Chaque fois qu'une Absence est créée, mise à jour ou supprimée, l'éligibilité
de l'étudiant concerné à l'examen (eligible_examen sur Inscription) doit être
recalculée pour refléter le nouveau total d'absences. Ce module branche les
récepteurs post_save et post_delete nécessaires.

Responsabilités :
  - Déclencher le recalcul d'éligibilité après chaque sauvegarde ou
    suppression d'Absence, différé via transaction.on_commit() pour éviter les
    écritures BDD imbriquées et garantir la cohérence (tous les changements
    sont visibles avant le recalcul).
  - Invalider le cache du tableau de bord admin des étudiants à risque
    (admin_dashboard:at_risk_count) chaque fois que les données d'absence
    changent.
  - Recalculer l'éligibilité pour toutes les inscriptions actives lorsque le
    seuil d'absence (seuil_absence) d'un cours est modifié.

Fait partie du système de gestion des absences UniAbsences.
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


# ── FIX P3-02 : Recalculer l'éligibilité lorsque le seuil du cours change ────────


@receiver(post_save, sender="academics.Cours")
def cours_seuil_changed(sender, instance, **kwargs):
    """
    Recalcule l'éligibilité à l'examen pour toutes les inscriptions actives lorsqu'un seuil de cours change.

    Déclenché lorsqu'une instance Cours est sauvegardée. Si la sauvegarde était
    une mise à jour partielle (update_fields est fourni) et que seuil_absence
    ne figure pas parmi les champs mis à jour, ce handler quitte immédiatement
    pour éviter un travail inutile.

    Side effects (différés via transaction.on_commit) :
      - Appelle recalculer_eligibilite() pour chaque Inscription active du cours.
      - Invalide le cache du compteur d'étudiants à risque du tableau de bord admin.

    Args:
        sender: La classe du modèle Cours.
        instance: L'instance Cours qui a été sauvegardée.
        **kwargs: Kwargs standards des signaux Django (update_fields, created, etc.).
    """
    # N'agir que si seuil_absence a pu changer (indice update_fields)
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and "seuil_absence" not in update_fields:
        return

    from apps.enrollments.models import Inscription

    inscriptions = Inscription.objects.filter(
        id_cours=instance,
        status=Inscription.Status.EN_COURS,
    ).select_related("id_cours")

    if not inscriptions.exists():
        return

    def _recalculate_all():
        """Recalcule l'éligibilité de chaque inscription et purge le cache du dashboard."""
        for ins in inscriptions:
            try:
                recalculer_eligibilite(ins)
            except Exception:
                logger.exception(
                    "Failed to recalculate eligibility for inscription %s after seuil change",
                    ins.id_inscription,
                )
        cache.delete(CACHE_KEY_AT_RISK)

    transaction.on_commit(_recalculate_all)


def _schedule_eligibility_recalc(inscription_pk):
    """
    Diffère le recalcul d'éligibilité après le commit de la transaction courante.

    Enregistre un callback via transaction.on_commit() pour que le recalcul
    ne s'exécute qu'une fois la transaction BDD écrivant le changement
    d'Absence entièrement validée. Cela garantit que les totaux d'absence
    agrégés sont à jour lorsque recalculer_eligibilite() les lit.

    Args:
        inscription_pk: Clé primaire de l'Inscription dont l'éligibilité doit
            être recalculée. Récupérée à neuf dans le callback pour éviter les
            données obsolètes.
    """

    def _recalcul():
        """Recharge l'inscription depuis la base et déclenche son recalcul d'éligibilité."""
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
    Recalcule l'éligibilité à l'examen après la création ou la mise à jour d'un enregistrement Absence.

    Utilise transaction.on_commit() pour différer l'exécution jusqu'à ce que la
    transaction BDD englobante soit entièrement validée, empêchant les
    écritures imbriquées et garantissant que tous les agrégats d'absence sont
    à jour avant l'exécution du recalcul.

    Invalide également le cache du compteur d'étudiants à risque du tableau de
    bord admin afin que le tableau de bord reflète les dernières données à la
    prochaine requête.

    Side effects:
      - Planifie recalculer_eligibilite() pour l'inscription associée.
      - Supprime la clé de cache admin_dashboard:at_risk_count.

    Args:
        sender: La classe du modèle Absence.
        instance: L'instance Absence qui a été sauvegardée.
        **kwargs: Kwargs standards des signaux Django (created, update_fields, etc.).
    """
    if instance.id_inscription_id:
        _schedule_eligibility_recalc(instance.id_inscription_id)
        cache.delete(CACHE_KEY_AT_RISK)


@receiver(post_delete, sender=Absence)
def absence_post_delete(sender, instance, **kwargs):
    """
    Recalcule l'éligibilité à l'examen après la suppression d'un enregistrement Absence.

    La suppression réduit le total d'heures d'absence pour une inscription
    (par ex. lorsqu'un professeur corrige un étudiant marqué absent par
    erreur). Le statut d'éligibilité doit être mis à jour afin que l'étudiant
    ne soit plus bloqué si le total corrigé descend sous le seuil.

    Side effects:
      - Planifie recalculer_eligibilite() pour l'inscription associée.
      - Supprime la clé de cache admin_dashboard:at_risk_count.

    Args:
        sender: La classe du modèle Absence.
        instance: L'instance Absence qui a été supprimée.
        **kwargs: Kwargs standards des signaux Django.
    """
    if instance.id_inscription_id:
        _schedule_eligibility_recalc(instance.id_inscription_id)
        cache.delete(CACHE_KEY_AT_RISK)
