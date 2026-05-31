"""
UniAbsences – scripts.utils
===========================

Shared bootstrapping utility for all standalone scripts in the ``scripts/``
tree.

Every script that imports Django models must call ``setup_django()`` before
any application import so that Django's app registry and settings are fully
initialised.  Centralising this logic here avoids duplicating the
``sys.path`` and ``DJANGO_SETTINGS_MODULE`` boilerplate in every file.

Part of: UniAbsences maintenance / utility layer.
"""

import os
import sys
from pathlib import Path


def setup_django() -> None:
    """Configure the Django environment for standalone scripts.

    Resolves the project root directory relative to this file's location,
    inserts it at the front of ``sys.path`` (if not already present), sets
    the ``DJANGO_SETTINGS_MODULE`` environment variable, and calls
    ``django.setup()`` so that the ORM and all installed apps become
    available.

    This function is idempotent with respect to ``sys.path`` – the root is
    inserted only once even if the function is called multiple times.

    Raises
    ------
    django.core.exceptions.ImproperlyConfigured
        If ``config.settings`` cannot be imported or is missing required
        settings keys.
    """
    # This file lives at <project_root>/scripts/utils.py, so:
    #   __file__          → .../scripts/utils.py
    #   .parent           → .../scripts/
    #   .parent.parent    → <project_root>/
    BASE_DIR = Path(__file__).resolve().parent.parent

    project_root = str(BASE_DIR)

    # Guard against inserting the same path twice when scripts import this
    # module more than once.
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Point Django at the project's main settings module.
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

    # Initialise the Django application registry (loads models, signals, etc.).
    import django
    django.setup()
