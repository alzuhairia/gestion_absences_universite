"""
Hub des vues accounts pour le système de comptes UniAbsences.

Ce module est un hub de réexport léger qui agrège les symboles de vues
publics depuis les deux sous-modules afin que ``accounts/urls.py`` puisse
importer depuis un emplacement stable unique, indépendamment de l'organisation
interne des fichiers.

Sous-modules
------------
``views_auth.py``    — ``RateLimitedLoginView``, ``CustomPasswordResetView``,
                       ``CustomPasswordResetConfirmView``, ``CustomPasswordChangeView``.
``views_profile.py`` — ``profile_view``, ``download_report_pdf``.

Fait partie du système de comptes UniAbsences.
"""

from apps.accounts.views_auth import (  # noqa: F401
    CustomPasswordChangeView,
    CustomPasswordResetConfirmView,
    CustomPasswordResetView,
    RateLimitedLoginView,
)
from apps.accounts.views_profile import (  # noqa: F401
    download_report_pdf,
    profile_view,
)
