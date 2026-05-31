"""
MFA views hub for the UniAbsences accounts system.

This module is a re-export hub — it imports all public 2FA view functions
from their respective sub-modules and re-exports them under a single namespace.
``accounts/urls.py`` imports from here so that URL routing code is decoupled
from the internal sub-module layout.

Sub-modules
-----------
``mfa_setup.py``    — ``setup_2fa`` (TOTP activation wizard), ``disable_2fa``.
``mfa_verify.py``   — ``verify_2fa`` (post-login TOTP gate).
``mfa_backup.py``   — ``backup_codes_view``, ``regenerate_backup_codes``.

Part of the UniAbsences accounts / MFA system.
"""

from .mfa_setup import disable_2fa, setup_2fa  # noqa: F401
from .mfa_verify import verify_2fa  # noqa: F401
from .mfa_backup import backup_codes_view, regenerate_backup_codes  # noqa: F401
