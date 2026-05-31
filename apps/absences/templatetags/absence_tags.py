"""
Absence Template Tag Library — apps/absences/templatetags/absence_tags.py

Part of the UniAbsences university attendance management system.

This module registers custom Django template filters that expose justification
deadline logic to the template layer.  By delegating calculations to the
service layer (``apps.absences.services``), templates remain free of business
logic and stay easy to maintain.

Usage in a template::

    {% load absence_tags %}

    {# Display the human-readable deadline date #}
    {{ absence|justification_deadline }}

    {# Conditionally show a "window closed" banner #}
    {% if absence|justification_expired %}
        <span class="badge bg-danger">Deadline passed</span>
    {% endif %}

    {# Provide the ISO 8601 deadline string for a JavaScript countdown timer #}
    <span data-deadline="{{ absence|justification_deadline_iso }}"></span>
"""
from django import template

from apps.absences.services import get_justification_deadline, is_justification_expired

register = template.Library()


@register.filter
def justification_deadline(absence):
    """
    Template filter: return the justification submission deadline date for an absence.

    Delegates to ``get_justification_deadline`` in the service layer so that
    the threshold constant (``JUSTIFICATION_DEADLINE_DAYS``) is maintained in
    a single place.

    Args:
        absence: ``apps.absences.models.Absence`` instance passed from the
            template context.

    Returns:
        datetime.date: the last date on which the student may submit a
        justification document for this absence.

    Example::

        {{ absence|justification_deadline }}
    """
    return get_justification_deadline(absence)


@register.filter
def justification_expired(absence):
    """
    Template filter: return whether the justification submission window has closed.

    Args:
        absence: ``apps.absences.models.Absence`` instance passed from the
            template context.

    Returns:
        bool: True if today is strictly after the deadline date (the window is
        closed and the student can no longer submit a justification document),
        False otherwise.

    Example::

        {% if absence|justification_expired %}
            <span>No longer justifiable</span>
        {% endif %}
    """
    return is_justification_expired(absence)


@register.filter
def justification_deadline_iso(absence):
    """
    Template filter: return the justification deadline as an ISO 8601 datetime
    string suitable for use with JavaScript countdown timers.

    The time component is fixed to 23:59:59 so that the countdown expires at
    the very end of the deadline day, giving the student the full calendar day.

    Args:
        absence: ``apps.absences.models.Absence`` instance passed from the
            template context.

    Returns:
        str: ISO 8601 datetime string in the format ``YYYY-MM-DDTHH:MM:SS``
        (e.g. ``"2024-11-15T23:59:59"``).

    Example::

        <span data-deadline="{{ absence|justification_deadline_iso }}"></span>
    """
    deadline = get_justification_deadline(absence)
    # Append end-of-day time so the JS countdown expires at 23:59:59 on the deadline date.
    return f"{deadline.isoformat()}T23:59:59"
