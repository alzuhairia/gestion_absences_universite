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


@register.filter
def justification_deadline_iso(absence):
    """Returns the deadline as ISO 8601 string (end of day) for JS countdown."""
    deadline = get_justification_deadline(absence)
    # End of deadline day: 23:59:59
    return f"{deadline.isoformat()}T23:59:59"
