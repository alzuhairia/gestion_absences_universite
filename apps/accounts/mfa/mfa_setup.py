"""
2FA activation and deactivation views for the UniAbsences MFA system.

This module handles the two lifecycle operations for TOTP-based two-factor
authentication: enabling it (``setup_2fa``) and disabling it (``disable_2fa``).

Views
-----
``setup_2fa``
    Two-step activation wizard.
    GET  — generates a random TOTP secret, stores it temporarily in the
           session (not in the database), and renders a QR code the user
           must scan with their authenticator app.
    POST — verifies the first TOTP code produced by the app.  On success,
           persists the secret to the database, generates backup codes, and
           redirects to the one-shot backup-code display page.
    The secret is intentionally not persisted until the user proves they can
    produce a valid code — this avoids "half-setup" accounts.

``disable_2fa``
    Deactivation after password confirmation.
    GET  — render the password-confirmation form.
    POST — validate the password, clear the TOTP secret and the
           ``two_factor_enabled`` flag, delete all backup codes, and
           redirect to the profile page.
    Password confirmation prevents a hijacked session from silently
    downgrading the user's account security.

Helpers
-------
``_role_base_template``
    Returns the name of the base Jinja2/Django template that matches the
    user's role so every 2FA page inherits the correct sidebar.

Part of the UniAbsences accounts / MFA system.
"""

import logging

import pyotp
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action

from ..models import TwoFactorBackupCode
from .mfa_service import (
    BACKUP_CODES_SESSION_KEY,
    SETUP_SECRET_SESSION_KEY,
    TOTP_ISSUER,
    VERIFIED_SESSION_KEY,
    _generate_backup_codes,
    _generate_qr_data_uri,
    _normalize_token,
)

logger = logging.getLogger(__name__)


def _role_base_template(user) -> str:
    """
    Return the role-appropriate base template name for 2FA pages.

    Each 2FA page must extend the correct base layout so it renders within
    the right sidebar (admin, secretary, instructor, or student).  If the
    user object does not carry a ``Role`` attribute (e.g. during testing with
    a mock user), the generic ``base.html`` is returned as a safe fallback.

    Parameters:
        user: The authenticated ``User`` instance (or any object with
              ``role`` and ``Role`` attributes).

    Returns:
        str: The template name to pass as ``base_template`` in context.
    """
    role = getattr(user, "role", None)
    Role = getattr(user, "Role", None)
    if Role is None:
        return "base.html"
    if role == Role.ADMIN:
        return "base_admin.html"
    if role == Role.SECRETAIRE:
        return "base_secretary.html"
    if role == Role.PROFESSEUR:
        return "base_instructor.html"
    if role == Role.ETUDIANT:
        return "base_student.html"
    return "base.html"


@login_required
@require_http_methods(["GET", "POST"])
def setup_2fa(request):
    """
    Two-step TOTP activation wizard.

    Step 1 — GET request
        A random 32-character Base32 TOTP secret is generated with
        ``pyotp.random_base32()`` and stored temporarily in the session under
        ``SETUP_SECRET_SESSION_KEY``.  A provisioning URI and QR-code data
        URI are rendered so the user can scan the code with their authenticator
        app (Google Authenticator, Authy, etc.).  The secret is **not** written
        to the database at this point.

    Step 2 — POST request
        The user submits the 6-digit TOTP code displayed by their app.  The
        submitted token is normalised (whitespace / non-digits stripped) and
        verified against the session-stored secret with a ±1 window (±30 s
        clock drift tolerance).

        On success (inside a single atomic transaction):
        1. The secret is persisted to ``user.two_factor_secret``.
        2. ``user.two_factor_enabled`` is set to ``True``.
        3. A fresh batch of backup codes is generated.
        4. The session secret is cleared, ``VERIFIED_SESSION_KEY`` is set to
           ``True``, and the plaintext backup codes are placed in the session
           for one-shot display.
        5. The session auth hash is rotated via ``update_session_auth_hash``.
        6. The action is recorded in the audit log.

    Parameters:
        request: The authenticated HTTP request (GET or POST).

    Returns:
        HttpResponse: The QR-code setup page (GET), a redirect to the profile
                      (already enabled), or a redirect to the backup-codes
                      display page (successful activation).
    """
    user = request.user

    # If 2FA is already active, there is nothing to set up.
    if user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs est deja activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        # Retrieve the provisional secret stored in the session during the GET step.
        secret = request.session.get(SETUP_SECRET_SESSION_KEY)
        token = _normalize_token(request.POST.get("token", ""))

        if not secret:
            # Session expired between the QR display and the code submission.
            messages.error(request, "La session de configuration a expire. Reessayez.")
            return redirect("accounts:setup_2fa")

        if not token or len(token) != 6:
            messages.error(request, "Veuillez saisir un code a 6 chiffres.")
            return redirect("accounts:setup_2fa")

        totp = pyotp.TOTP(secret)
        # valid_window=1 allows a ±30 s tolerance for clock skew between the
        # server and the user's authenticator device.
        if not totp.verify(token, valid_window=1):
            messages.error(
                request,
                "Code invalide. Verifiez l'heure de votre telephone et reessayez.",
            )
            return redirect("accounts:setup_2fa")

        # Persist the secret and enable 2FA atomically so there is no state
        # where the flag is set but the secret is absent (or vice versa).
        with transaction.atomic():
            user.two_factor_secret = secret
            user.two_factor_enabled = True
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            new_codes = _generate_backup_codes(user)

        # Clean up the provisional secret from the session.
        request.session.pop(SETUP_SECRET_SESSION_KEY, None)
        # Mark this session as 2FA-verified so the middleware stops redirecting.
        request.session[VERIFIED_SESSION_KEY] = True
        # Store plaintext codes for the one-shot backup-code display page.
        request.session[BACKUP_CODES_SESSION_KEY] = new_codes
        # Rotate the session auth hash to keep the session valid after this
        # security-relevant change.
        update_session_auth_hash(request, user)

        log_action(
            user,
            "Activation de l'authentification a deux facteurs (TOTP)",
            request,
            niveau="INFO",
            objet_type="USER",
            objet_id=user.pk,
        )

        messages.success(request, "Authentification a deux facteurs activee avec succes.")
        return redirect("accounts:backup_codes")

    # GET — generate a new provisional secret and render the QR code.
    secret = pyotp.random_base32()
    # Store the secret in the session so it can be verified on the next POST.
    request.session[SETUP_SECRET_SESSION_KEY] = secret

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)
    # Convert the provisioning URI to an inline base64 data URI for the <img> tag.
    qr_data_uri = _generate_qr_data_uri(provisioning_uri)

    return render(
        request,
        "accounts/setup_2fa.html",
        {
            "qr_data_uri": qr_data_uri,
            "secret": secret,           # shown as a manual entry fallback
            "issuer": TOTP_ISSUER,
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def disable_2fa(request):
    """
    Deactivate TOTP 2FA after the user confirms their current password.

    The password confirmation step prevents an attacker with a valid but
    hijacked session (e.g. unattended browser) from silently downgrading
    the account's security posture.

    GET
        Render the confirmation form.

    POST
        Validate the submitted password.  On failure, log a WARNING audit
        event and return the form with an error (HTTP 400) so the client
        can retry.

        On success (inside a single atomic transaction):
        1. ``user.two_factor_secret`` is cleared.
        2. ``user.two_factor_enabled`` is set to ``False``.
        3. All ``TwoFactorBackupCode`` records for the user are deleted.
        4. ``VERIFIED_SESSION_KEY`` is removed from the session.
        5. The session auth hash is rotated via ``update_session_auth_hash``.
        6. The action is recorded in the audit log at WARNING severity.

    Parameters:
        request: The authenticated HTTP request (GET or POST).

    Returns:
        HttpResponse: The confirmation form, a redirect to the profile on
                      success, or a redirect to the profile if 2FA is not
                      currently enabled.
    """
    user = request.user

    # Guard: nothing to disable if 2FA is not active.
    if not user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs n'est pas activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
            # Audit a failed attempt — repeated failures could indicate
            # an attacker trying to weaken the account's 2FA protection.
            log_action(
                user,
                "Tentative de desactivation 2FA avec mot de passe incorrect",
                request,
                niveau="WARNING",
                objet_type="USER",
                objet_id=user.pk,
            )
            messages.error(request, "Mot de passe incorrect.")
            return render(
                request,
                "accounts/disable_2fa.html",
                {"base_template": _role_base_template(user)},
                status=400,
            )

        with transaction.atomic():
            # Clear all 2FA fields atomically to leave no half-disabled state.
            user.two_factor_secret = ""
            user.two_factor_enabled = False
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            # Invalidate all backup codes — they are only valid while 2FA is on.
            TwoFactorBackupCode.objects.filter(user=user).delete()

        # Remove the 2FA verification flag so the middleware reflects the
        # new state immediately for any subsequent request in this session.
        request.session.pop(VERIFIED_SESSION_KEY, None)
        # Rotate the session auth hash after this security-relevant change.
        update_session_auth_hash(request, user)

        log_action(
            user,
            "Desactivation de l'authentification a deux facteurs",
            request,
            niveau="WARNING",
            objet_type="USER",
            objet_id=user.pk,
        )

        messages.success(request, "Authentification a deux facteurs desactivee.")
        return redirect("accounts:profile")

    return render(
        request,
        "accounts/disable_2fa.html",
        {"base_template": _role_base_template(user)},
    )
