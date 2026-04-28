"""
Package MFA/2FA pour UniAbsences.

Organisation :
  mfa_service.py  — constantes TOTP, génération QR, codes de secours (logique pure)
  mfa_views.py    — re-export hub → mfa_setup + mfa_verify + mfa_backup
    mfa_setup.py  — setup_2fa (activation, QR scan) + disable_2fa
    mfa_verify.py — verify_2fa (gate post-login, TOTP + codes de secours)
    mfa_backup.py — backup_codes_view (affichage one-shot) + regenerate_backup_codes
"""
from .mfa_service import (
    SETUP_SECRET_SESSION_KEY,
    VERIFIED_SESSION_KEY,
    ATTEMPTS_SESSION_KEY,
    MAX_VERIFY_ATTEMPTS,
    TOTP_ISSUER,
    BACKUP_CODES_SESSION_KEY,
    BACKUP_CODE_LENGTH,
    _generate_qr_data_uri,
    _normalize_token,
    _normalize_backup_code,
    _format_backup_code,
    _generate_backup_codes,
    _consume_backup_code,
)
from .mfa_views import (
    setup_2fa,
    verify_2fa,
    disable_2fa,
    backup_codes_view,
    regenerate_backup_codes,
)
