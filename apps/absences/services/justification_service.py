"""
Service de délai de justification — apps/absences/services/justification_service.py

Fait partie du système universitaire de gestion des présences UniAbsences.

Responsabilité unique : calculer et vérifier le délai de soumission du
justificatif d'absence d'un étudiant.

Règle métier :
    Un étudiant dispose de ``JUSTIFICATION_DEADLINE_DAYS`` jours calendaires
    après la date de la séance pour soumettre un document justificatif. Passé
    ce délai, la fenêtre de soumission est fermée et l'absence ne peut plus
    être justifiée. Le délai est inclusif — un étudiant peut soumettre le
    dernier jour lui-même.
"""
import datetime

from django.utils import timezone

# Nombre de jours calendaires après la date de la séance pendant lesquels
# l'étudiant peut soumettre un document justificatif. Passé cette fenêtre,
# l'absence est traitée définitivement comme non justifiée.
JUSTIFICATION_DEADLINE_DAYS = 3


def get_justification_deadline(absence):
    """
    Retourne la dernière date à laquelle l'étudiant peut soumettre un document justificatif pour une absence donnée.

    Le délai est calculé comme :
        deadline = date_seance + JUSTIFICATION_DEADLINE_DAYS

    Args :
        absence : instance ``apps.absences.models.Absence`` dont le ``id_seance``
            relié doit être accessible (fournit ``date_seance``).

    Retour :
        datetime.date : la date inclusive de fin de délai pour la soumission du document.
    """
    return absence.id_seance.date_seance + datetime.timedelta(
        days=JUSTIFICATION_DEADLINE_DAYS
    )


def is_justification_expired(absence):
    """
    Indique si la fenêtre de soumission de justificatif est fermée pour une absence.

    Le jour limite est inclusif : un étudiant qui soumet le jour même du délai
    se trouve encore dans la fenêtre autorisée.

    Args :
        absence : instance ``apps.absences.models.Absence`` dont le ``id_seance``
            relié doit être accessible.

    Retour :
        bool : True si aujourd'hui est strictement après la date limite
        (fenêtre fermée), False si l'étudiant peut encore soumettre un
        document justificatif.
    """
    deadline = get_justification_deadline(absence)
    today = timezone.localdate()
    # Comparaison stricte : today > deadline signifie que la fenêtre est fermée.
    return today > deadline
