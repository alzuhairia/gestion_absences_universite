"""
MFA / 2FA package for the UniAbsences accounts system.

This package contains all logic related to TOTP-based two-factor
authentication (RFC 6238) and one-time backup codes.

Package layout
--------------
mfa_service.py
    HTTP-independent service layer: TOTP verification, backup-code generation
    and consumption, QR-code data-URI helper, and the session-key constants
    shared by middleware and views.

mfa_views.py
    Re-export hub — aggregates all public view functions under a single
    namespace so that ``accounts/urls.py`` can import from one place.

    Delegates to:

    mfa_setup.py
        ``setup_2fa``   — activation wizard (QR scan + first-TOTP confirm).
        ``disable_2fa`` — deactivation after password confirmation.

    mfa_verify.py
        ``verify_2fa``  — post-login TOTP / backup-code verification gate.

    mfa_backup.py
        ``backup_codes_view``       — one-shot display of newly generated codes.
        ``regenerate_backup_codes`` — invalidate all codes and issue a new batch.

Part of the UniAbsences accounts system.
"""
