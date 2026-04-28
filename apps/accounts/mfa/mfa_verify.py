"""
Vérification du code TOTP post-login — gate 2FA.

Fonctionnalité :
  - verify_2fa : affiché APRÈS le login Django ; l'utilisateur est déjà
                 authentifié mais sa session n'est pas encore marquée 2FA-vérifiée.
                 Accepte les codes TOTP (6 chiffres) et les codes de secours.

Sécurité :
  - MAX_VERIFY_ATTEMPTS tentatives avant déconnexion forcée
  - Code de secours consommé à usage unique (via _consume_backup_code)
  - Avertissement si il reste ≤ 2 codes de secours
"""
import logging

import pyotp
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.audits.utils import log_action

from ..models import TwoFactorBackupCode
from .mfa_service import (
    ATTEMPTS_SESSION_KEY,
    BACKUP_CODE_LENGTH,
    MAX_VERIFY_ATTEMPTS,
    VERIFIED_SESSION_KEY,
    _consume_backup_code,
    _normalize_backup_code,
    _normalize_token,
)

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def verify_2fa(request):
    """
    Page de vérification du code TOTP affichée APRÈS le login Django.

    L'utilisateur est déjà authentifié (request.user.is_authenticated)
    mais sa session n'est pas encore marquée 2FA-validée. Le middleware
    TwoFactorMiddleware le redirige ici tant que `2fa_verified` n'est pas True.

    On NE met PAS @login_required car le middleware s'en charge en amont,
    mais on vérifie quand même is_authenticated par défense en profondeur.
    """
    user = request.user

    if not user.is_authenticated:
        return redirect("accounts:login")

    if not getattr(user, "two_factor_enabled", False):
        request.session[VERIFIED_SESSION_KEY] = True
        return redirect("dashboard:index")

    if request.session.get(VERIFIED_SESSION_KEY):
        return redirect("dashboard:index")

    if request.method == "POST":
        raw_code = request.POST.get("token", "")
        attempts = int(request.session.get(ATTEMPTS_SESSION_KEY, 0))

        if attempts >= MAX_VERIFY_ATTEMPTS:
            log_action(
                user,
                "CRITIQUE: 2FA verification - depassement du nombre de tentatives",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.pk,
            )
            logout(request)
            messages.error(request, "Trop de tentatives invalides. Vous avez ete deconnecte.")
            return redirect("accounts:login")

        token = _normalize_token(raw_code)
        method_used = None

        if len(token) == 6:
            totp = pyotp.TOTP(user.two_factor_secret)
            if totp.verify(token, valid_window=1):
                method_used = "TOTP"

        if method_used is None:
            backup_candidate = _normalize_backup_code(raw_code)
            if len(backup_candidate) == BACKUP_CODE_LENGTH:
                if _consume_backup_code(user, backup_candidate):
                    method_used = "BACKUP"

        if method_used is None:
            request.session[ATTEMPTS_SESSION_KEY] = attempts + 1
            log_action(
                user,
                f"2FA verification echouee (tentative {attempts + 1}/{MAX_VERIFY_ATTEMPTS})",
                request,
                niveau="WARNING",
                objet_type="USER",
                objet_id=user.pk,
            )
            messages.error(request, "Code invalide.")
            return render(request, "accounts/verify_2fa.html", status=400)

        request.session[VERIFIED_SESSION_KEY] = True
        request.session.pop(ATTEMPTS_SESSION_KEY, None)
        log_action(
            user,
            f"2FA verification reussie ({method_used})",
            request,
            niveau="INFO" if method_used == "TOTP" else "WARNING",
            objet_type="USER",
            objet_id=user.pk,
        )

        if method_used == "BACKUP":
            remaining = TwoFactorBackupCode.objects.filter(user=user, used=False).count()
            if remaining == 0:
                messages.warning(
                    request,
                    "Vous avez utilise votre dernier code de secours. "
                    "Regenerez des codes depuis votre profil.",
                )
            elif remaining <= 2:
                messages.warning(
                    request,
                    f"Il ne vous reste que {remaining} code(s) de secours. "
                    "Pensez a en regenerer.",
                )
        return redirect("dashboard:index")

    return render(request, "accounts/verify_2fa.html")
