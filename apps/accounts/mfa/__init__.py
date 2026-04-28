"""
Package MFA/2FA pour UniAbsences.

Organisation :
  mfa_service.py  — constantes TOTP, génération QR, codes de secours (logique pure)
  mfa_views.py    — re-export hub → mfa_setup + mfa_verify + mfa_backup
    mfa_setup.py  — setup_2fa (activation, QR scan) + disable_2fa
    mfa_verify.py — verify_2fa (gate post-login, TOTP + codes de secours)
    mfa_backup.py — backup_codes_view (affichage one-shot) + regenerate_backup_codes
"""
