"""
Bibliothèque de tags de template pour les absences — apps/absences/templatetags/absence_tags.py

Fait partie du système de gestion des absences universitaires UniAbsences.

Ce module enregistre des filtres de template Django personnalisés qui exposent
la logique de date limite de justification à la couche de templates.  En
déléguant les calculs à la couche service (``apps.absences.services``), les
templates restent exempts de logique métier et faciles à maintenir.

Utilisation dans un template ::

    {% load absence_tags %}

    {# Affiche la date limite en format lisible #}
    {{ absence|justification_deadline }}

    {# Affiche conditionnellement une bannière "délai dépassé" #}
    {% if absence|justification_expired %}
        <span class="badge bg-danger">Délai dépassé</span>
    {% endif %}

    {# Fournit la date limite au format ISO 8601 pour un compte à rebours JavaScript #}
    <span data-deadline="{{ absence|justification_deadline_iso }}"></span>
"""
from django import template

from apps.absences.services import get_justification_deadline, is_justification_expired

register = template.Library()


@register.filter
def justification_deadline(absence):
    """
    Filtre de template : retourne la date limite de dépôt du justificatif
    pour une absence.

    Délègue à ``get_justification_deadline`` dans la couche service afin que
    la constante de seuil (``JUSTIFICATION_DEADLINE_DAYS``) soit maintenue
    à un seul endroit.

    Args:
        absence: Instance ``apps.absences.models.Absence`` passée depuis le
            contexte du template.

    Returns:
        datetime.date : dernière date à laquelle l'étudiant peut déposer un
        document de justification pour cette absence.

    Exemple ::

        {{ absence|justification_deadline }}
    """
    return get_justification_deadline(absence)


@register.filter
def justification_expired(absence):
    """
    Filtre de template : indique si la fenêtre de dépôt du justificatif
    est fermée.

    Args:
        absence: Instance ``apps.absences.models.Absence`` passée depuis le
            contexte du template.

    Returns:
        bool : True si la date du jour est strictement postérieure à la date
        limite (la fenêtre est fermée et l'étudiant ne peut plus déposer de
        document de justification), False sinon.

    Exemple ::

        {% if absence|justification_expired %}
            <span>Plus justifiable</span>
        {% endif %}
    """
    return is_justification_expired(absence)


@register.filter
def justification_deadline_iso(absence):
    """
    Filtre de template : retourne la date limite de justification sous forme
    de chaîne datetime ISO 8601 utilisable avec un compte à rebours JavaScript.

    La composante horaire est fixée à 23:59:59 afin que le compte à rebours
    expire à la toute fin de la journée butoir, laissant à l'étudiant la
    journée complète.

    Args:
        absence: Instance ``apps.absences.models.Absence`` passée depuis le
            contexte du template.

    Returns:
        str : chaîne datetime ISO 8601 au format ``YYYY-MM-DDTHH:MM:SS``
        (p. ex. ``"2024-11-15T23:59:59"``).

    Exemple ::

        <span data-deadline="{{ absence|justification_deadline_iso }}"></span>
    """
    deadline = get_justification_deadline(absence)
    # Ajoute l'heure de fin de journée pour que le compte à rebours JS expire à 23:59:59 à la date butoir.
    return f"{deadline.isoformat()}T23:59:59"
