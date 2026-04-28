"""
FICHIER : apps/accounts/mfa/mfa_views.py
RESPONSABILITE : Re-export centralisé des vues 2FA/TOTP.

Organisation :
  mfa_setup.py  — setup_2fa (activation) + disable_2fa + _role_base_template
  mfa_verify.py — verify_2fa (gate post-login)
  mfa_backup.py — backup_codes_view + regenerate_backup_codes
"""

from .mfa_setup import disable_2fa, setup_2fa  # noqa: F401
from .mfa_verify import verify_2fa  # noqa: F401
from .mfa_backup import backup_codes_view, regenerate_backup_codes  # noqa: F401
