"""
Shared utilities used across multiple apps.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast

from django import forms
from django.core.paginator import EmptyPage, PageNotAnInteger


def safe_get_page(paginator, page_number):
    """Return the requested page, falling back to page 1 for any invalid input."""
    try:
        return paginator.page(page_number or 1)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)


def model_choice_field(form, name) -> forms.ModelChoiceField:
    """
    Return form.fields[name] typed as a model choice field, so its queryset can
    be set or read (form.fields only exposes the generic Field type).
    ModelMultipleChoiceField is a subclass, so this covers both.
    """
    return cast(forms.ModelChoiceField, form.fields[name])


def parse_hours(raw) -> Decimal:
    """
    Parse a duration in hours typed by a user ("1.5" or "1,5") into a finite
    Decimal rounded to 0.01. Raises ValueError for anything else, including
    "nan" and "inf" (which float() would accept).
    """
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
        if not value.is_finite():
            raise ValueError(f"invalid duration: {raw!r}")
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"invalid duration: {raw!r}") from exc
