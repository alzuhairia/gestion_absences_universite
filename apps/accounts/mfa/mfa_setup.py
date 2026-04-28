"""
Activation et désactivation de la 2FA — vue utilisateur.

Fonctionnalités :
  - setup_2fa   : activer la 2FA (génère secret + QR code, demande vérification du premier TOTP)
  - disable_2fa : désactiver la 2FA après confirmation par mot de passe
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
    """Renvoie le base template à étendre selon le rôle pour conserver la sidebar."""
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
    Active la 2FA pour l'utilisateur connecté.

    GET  : génère un secret aléatoire (stocké en session, PAS encore en DB),
           crée le QR code de provisioning et l'affiche.
    POST : vérifie le code TOTP saisi avec le secret en session ;
           si OK, persiste le secret sur l'utilisateur et marque la session
           comme vérifiée 2FA.

    Sécurité :
        - Le secret n'est jamais persisté en DB tant que l'utilisateur n'a pas
          prouvé qu'il a bien scanné le QR (vérification du premier code).
        - Si la 2FA est déjà activée, on redirige vers le profil.
    """
    user = request.user

    if user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs est deja activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        secret = request.session.get(SETUP_SECRET_SESSION_KEY)
        token = _normalize_token(request.POST.get("token", ""))

        if not secret:
            messages.error(request, "La session de configuration a expire. Reessayez.")
            return redirect("accounts:setup_2fa")

        if not token or len(token) != 6:
            messages.error(request, "Veuillez saisir un code a 6 chiffres.")
            return redirect("accounts:setup_2fa")

        totp = pyotp.TOTP(secret)
        if not totp.verify(token, valid_window=1):
            messages.error(
                request,
                "Code invalide. Verifiez l'heure de votre telephone et reessayez.",
            )
            return redirect("accounts:setup_2fa")

        with transaction.atomic():
            user.two_factor_secret = secret
            user.two_factor_enabled = True
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            new_codes = _generate_backup_codes(user)

        request.session.pop(SETUP_SECRET_SESSION_KEY, None)
        request.session[VERIFIED_SESSION_KEY] = True
        request.session[BACKUP_CODES_SESSION_KEY] = new_codes
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

    # GET : (re)générer un secret et afficher le QR
    secret = pyotp.random_base32()
    request.session[SETUP_SECRET_SESSION_KEY] = secret

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)
    qr_data_uri = _generate_qr_data_uri(provisioning_uri)

    return render(
        request,
        "accounts/setup_2fa.html",
        {
            "qr_data_uri": qr_data_uri,
            "secret": secret,
            "issuer": TOTP_ISSUER,
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def disable_2fa(request):
    """
    Désactive la 2FA après confirmation par mot de passe.

    Le mot de passe est demandé pour éviter qu'une session volée/oubliée
    puisse désactiver la 2FA en un clic.
    """
    user = request.user

    if not user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs n'est pas activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
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
            user.two_factor_secret = ""
            user.two_factor_enabled = False
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            TwoFactorBackupCode.objects.filter(user=user).delete()

        request.session.pop(VERIFIED_SESSION_KEY, None)
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
