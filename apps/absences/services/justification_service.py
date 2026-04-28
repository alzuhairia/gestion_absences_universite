"""
Service : Délais de justification des absences.

Responsabilité unique : calculer et vérifier le délai accordé
à l'étudiant pour soumettre un justificatif après une absence.
"""
import datetime

from django.utils import timezone

# Nombre de jours après la date d'absence pour soumettre une justification
JUSTIFICATION_DEADLINE_DAYS = 3


def get_justification_deadline(absence):
    """
    Retourne la date limite (date) à laquelle l'étudiant doit soumettre
    son justificatif.  deadline = date_absence + JUSTIFICATION_DEADLINE_DAYS.
    """
    return absence.id_seance.date_seance + datetime.timedelta(
        days=JUSTIFICATION_DEADLINE_DAYS
    )


def is_justification_expired(absence):
    """
    Retourne True si le délai de justification est dépassé pour cette absence.
    L'étudiant dispose jusqu'à la fin du jour limite (inclusif).
    """
    deadline = get_justification_deadline(absence)
    today = timezone.localdate()
    return today > deadline
