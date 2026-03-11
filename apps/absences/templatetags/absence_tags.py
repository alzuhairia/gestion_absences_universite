from django import template

from apps.absences.services import get_justification_deadline, is_justification_expired

register = template.Library()


@register.filter
def justification_deadline(absence):
    """Returns the justification deadline date for an absence."""
    return get_justification_deadline(absence)


@register.filter
def justification_expired(absence):
    """Returns True if the justification deadline has passed."""
    return is_justification_expired(absence)
