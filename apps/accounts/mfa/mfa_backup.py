"""
Backup-code management views for the UniAbsences MFA system.

This module handles the two user-facing views related to TOTP backup codes:
the one-shot display page shown immediately after code generation, and the
regeneration flow that lets users invalidate all existing codes and issue a
fresh batch after confirming their password.

Views
-----
``backup_codes_view``
    GET-only.  Reads the newly generated plaintext codes from the session
    (placed there by ``setup_2fa`` or ``regenerate_backup_codes``), formats
    them for display, clears the session key immediately, and renders the
    template.  If the session key is absent the user is redirected to their
    profile — codes are intentionally not stored and cannot be recovered.

``regenerate_backup_codes``
    GET  — render the confirmation form (requires password entry).
    POST — validate the password, generate a new batch of codes atomically,
           store the plaintext codes in the session, and redirect to
           ``backup_codes_view`` for one-shot display.

Part of the UniAbsences accounts / MFA system.
"""

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action

from .mfa_service import (
    BACKUP_CODES_SESSION_KEY,
    _format_backup_code,
    _generate_backup_codes,
)
from .mfa_setup import _role_base_template

logger = logging.getLogger(__name__)


@login_required
@require_http_methods(["GET"])
def backup_codes_view(request):
    """
    Display the newly generated backup codes exactly once.

    This view is the landing page after 2FA setup or code regeneration.
    The plaintext codes are stored in the session under ``BACKUP_CODES_SESSION_KEY``
    by the upstream view, retrieved here, formatted for display, and then
    immediately removed from the session so they cannot be viewed again on
    a page refresh or a subsequent visit.

    If the session key is absent (user navigated directly or already viewed
    the codes), a warning is shown and the user is redirected to their profile
    page with instructions to regenerate the codes if needed.

    Only accessible when the user's account already has 2FA enabled — guards
    against direct URL access before 2FA setup is complete.

    Parameters:
        request: The authenticated GET request.

    Returns:
        HttpResponse: The rendered ``accounts/backup_codes.html`` template
                      with the formatted codes, or a redirect to the profile.
    """
    user = request.user

    # Guard: must have 2FA enabled to view backup codes.
    if not user.two_factor_enabled:
        return redirect("accounts:profile")

    raw_codes = request.session.get(BACKUP_CODES_SESSION_KEY)
    if not raw_codes:
        # Codes were already viewed or were never stored (direct URL access).
        messages.info(
            request,
            "Les codes de secours ne peuvent etre affiches qu'une seule fois "
            "apres generation. Regenerez-les si vous les avez perdus.",
        )
        return redirect("accounts:profile")

    # Remove the codes from the session immediately so they cannot be revisited.
    request.session.pop(BACKUP_CODES_SESSION_KEY, None)

    # Format each raw 10-char code as "XXXXX-XXXXX" for readability.
    formatted = [_format_backup_code(c) for c in raw_codes]

    return render(
        request,
        "accounts/backup_codes.html",
        {
            "codes": formatted,
            # Pass the role-appropriate base template so the page inherits
            # the correct sidebar and navigation layout.
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def regenerate_backup_codes(request):
    """
    Regenerate all backup codes after password confirmation.

    This view is a security-sensitive operation: generating a new batch
    immediately invalidates **all** existing backup codes (used or not).
    Password confirmation is required to prevent an attacker with a hijacked
    authenticated session from silently invalidating the user's recovery codes.

    GET
        Render the password-confirmation form.

    POST
        Validate the submitted password.  On failure, log the attempt at
        WARNING severity and return the form with an error (HTTP 400).
        On success, generate a new batch of backup codes, store the
        plaintext codes in the session for one-shot display, log the
        action, and redirect to ``backup_codes_view``.

    Parameters:
        request: The authenticated HTTP request (GET or POST).

    Returns:
        HttpResponse: The confirmation form, a redirect to ``backup_codes_view``
                      on success, or a redirect to the profile if 2FA is not
                      enabled.
    """
    user = request.user

    # Guard: regeneration only makes sense when 2FA is active.
    if not user.two_factor_enabled:
        messages.info(request, "Activez d'abord l'authentification a deux facteurs.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
            # Log the failed attempt for the security audit trail.
            log_action(
                user,
                "Tentative de regeneration des codes de secours avec mot de passe incorrect",
                request,
                niveau="WARNING",
                objet_type="USER",
                objet_id=user.pk,
            )
            messages.error(request, "Mot de passe incorrect.")
            return render(
                request,
                "accounts/regenerate_backup_codes.html",
                {"base_template": _role_base_template(user)},
                status=400,
            )

        # Generate a new batch — all existing codes are deleted atomically.
        new_codes = _generate_backup_codes(user)
        # Store plaintext codes in the session for a single display round-trip.
        request.session[BACKUP_CODES_SESSION_KEY] = new_codes

        log_action(
            user,
            "Regeneration des codes de secours 2FA",
            request,
            niveau="INFO",
            objet_type="USER",
            objet_id=user.pk,
        )
        messages.success(request, "Nouveaux codes de secours generes.")
        return redirect("accounts:backup_codes")

    return render(
        request,
        "accounts/regenerate_backup_codes.html",
        {"base_template": _role_base_template(user)},
    )
