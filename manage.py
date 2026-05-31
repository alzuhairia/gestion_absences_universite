#!/usr/bin/env python
"""
Django management entry point for the UniAbsences project.

This script is the standard Django command-line utility. It bootstraps
Django's settings module and delegates execution to Django's management
command infrastructure.

Part of the UniAbsences project root.
"""

import os
import sys


def main():
    """
    Configure Django settings and execute the requested management command.

    Sets the DJANGO_SETTINGS_MODULE environment variable to the project's
    settings package if it has not already been set, then hands off to
    Django's ``execute_from_command_line`` with the original ``sys.argv``.

    Raises:
        ImportError: If Django is not installed or the virtual environment
            is not activated.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
