"""
Shared utilities used across multiple apps.
"""

from django.core.paginator import EmptyPage, PageNotAnInteger


def safe_get_page(paginator, page_number):
    """Return the requested page, falling back to page 1 for any invalid input."""
    try:
        return paginator.page(page_number or 1)
    except (PageNotAnInteger, EmptyPage):
        return paginator.page(1)
