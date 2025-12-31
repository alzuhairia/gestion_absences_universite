"""
Signals Django pour la gestion automatique des absences.

IMPORTANT POUR LA SOUTENANCE :
Les signals permettent d'automatiser certaines actions lors de la création/modification
d'objets. Ici, le signal garantit que l'éligibilité à l'examen est toujours à jour.
"""
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Absence
from .services import recalculer_eligibilite

@receiver(post_save, sender=Absence)
def absence_post_save(sender, instance, **kwargs):
    """
    Signal déclenché après chaque sauvegarde d'une Absence.
    
    IMPORTANT POUR LA SOUTENANCE :
    Ce signal garantit la cohérence des données :
    - Après chaque création/modification d'absence, l'éligibilité à l'examen est recalculée
    - Cela évite les incohérences (ex: étudiant bloqué alors que son taux est < 40%)
    - Le recalcul est automatique et transparent pour l'utilisateur
    
    Logique :
    1. Une absence est créée ou modifiée
    2. Le signal est déclenché automatiquement
    3. La fonction recalculer_eligibilite() est appelée
    4. L'éligibilité de l'étudiant est mise à jour si nécessaire
    
    Pourquoi utiliser un signal ?
    - Centralisation : la logique de recalcul est au même endroit
    - Automatisation : pas besoin d'appeler manuellement le recalcul
    - Cohérence : garantit que l'éligibilité est toujours à jour
    
    Args:
        sender: Le modèle qui a envoyé le signal (Absence)
        instance: L'instance d'Absence qui vient d'être sauvegardée
        **kwargs: Arguments supplémentaires du signal
    """
    # Appel automatique du service de recalcul de l'éligibilité
    # Cela garantit que l'éligibilité est toujours à jour après chaque modification d'absence
    recalculer_eligibilite(instance.id_inscription)