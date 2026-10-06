"""
Shared utilities used across multiple apps.
"""

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
