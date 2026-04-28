"""
Gestion des codes de secours 2FA.

Fonctionnalités :
  - backup_codes_view       : affichage one-shot des codes après activation/régénération
  - regenerate_backup_codes : régénérer tous les codes de secours après confirmation par mot de passe
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
    Page affichée UNE SEULE FOIS après :
      - l'activation de la 2FA (setup_2fa)
      - une régénération (regenerate_backup_codes)

    Les codes en clair sont récupérés de la session puis la clé session est
    effacée immédiatement après le rendu — ils ne pourront plus être revus.
    Si la session ne contient pas de codes, on redirige vers le profil.
    """
    user = request.user
    if not user.two_factor_enabled:
        return redirect("accounts:profile")

    raw_codes = request.session.get(BACKUP_CODES_SESSION_KEY)
    if not raw_codes:
        messages.info(
            request,
            "Les codes de secours ne peuvent etre affiches qu'une seule fois "
            "apres generation. Regenerez-les si vous les avez perdus.",
        )
        return redirect("accounts:profile")

    request.session.pop(BACKUP_CODES_SESSION_KEY, None)

    formatted = [_format_backup_code(c) for c in raw_codes]

    return render(
        request,
        "accounts/backup_codes.html",
        {
            "codes": formatted,
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def regenerate_backup_codes(request):
    """
    Régénère les codes de secours après confirmation par mot de passe.
    Invalide immédiatement TOUS les anciens codes (utilisés ou non).
    """
    user = request.user
    if not user.two_factor_enabled:
        messages.info(request, "Activez d'abord l'authentification a deux facteurs.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
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

        new_codes = _generate_backup_codes(user)
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
