"""
FICHIER : apps/accounts/views_2fa.py
RESPONSABILITE : Vues pour l'authentification a deux facteurs (TOTP)
FONCTIONNALITES PRINCIPALES :
  - setup_2fa : generation du secret + QR code, activation apres verification
  - verify_2fa : verification du code TOTP apres login (gate post-login)
  - disable_2fa : desactivation 2FA avec confirmation par mot de passe
DEPENDANCES CLES : pyotp (TOTP), qrcode (PNG QR), apps.audits.utils.log_action
"""

import base64
import io
import logging

import pyotp
import qrcode
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from apps.audits.utils import log_action

logger = logging.getLogger(__name__)


def _role_base_template(user) -> str:
    """Renvoie le base template a etendre selon le role pour conserver la sidebar."""
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


# ─── Constants ──────────────────────────────────────────────────────────────

#: Cle de session ou est stocke le secret temporaire pendant l'enrolment.
SETUP_SECRET_SESSION_KEY = "_2fa_setup_secret"

#: Cle de session: True une fois le code TOTP verifie pour la session courante.
VERIFIED_SESSION_KEY = "2fa_verified"

#: Cle de session: nombre de tentatives de verification echouees.
ATTEMPTS_SESSION_KEY = "_2fa_attempts"

#: Nombre maximum d'essais avant deconnexion automatique.
MAX_VERIFY_ATTEMPTS = 5

#: Nom de l'emetteur affiche dans l'application TOTP (Google Authenticator, Authy).
TOTP_ISSUER = "UniAbsences"


# ─── Helpers ────────────────────────────────────────────────────────────────


def _generate_qr_data_uri(uri: str) -> str:
    """
    Encode un URI de provisioning TOTP en PNG QR code, retourne un data-URI base64.

    Le QR n'est jamais ecrit sur le disque : tout se fait en memoire pour eviter
    les fuites de secrets via le filesystem.
    """
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def _normalize_token(raw: str) -> str:
    """Strip whitespace and keep only digits — paste-friendly."""
    if not raw:
        return ""
    return "".join(ch for ch in raw if ch.isdigit())[:6]


# ─── Vue 1 : Setup 2FA (enrolment) ──────────────────────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def setup_2fa(request):
    """
    Active la 2FA pour l'utilisateur connecte.

    GET  : genere un secret aleatoire (stocke en session, PAS encore en DB),
           cree le QR code de provisioning et l'affiche.
    POST : verifie le code TOTP saisi avec le secret en session ;
           si OK, persiste le secret sur l'utilisateur et marque la session
           comme verifiee 2FA.

    Securite :
        - Le secret n'est jamais persiste en DB tant que l'utilisateur n'a pas
          prouve qu'il a bien scanne le QR (verification du premier code).
        - Si la 2FA est deja activee, on redirige vers les parametres pour
          eviter d'ecraser un secret existant par accident.
    """
    user = request.user

    if user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs est deja activee.")
        return redirect("accounts:profile")

    # POST : verification du code et activation
    if request.method == "POST":
        secret = request.session.get(SETUP_SECRET_SESSION_KEY)
        token = _normalize_token(request.POST.get("token", ""))

        if not secret:
            messages.error(
                request,
                "La session de configuration a expire. Reessayez.",
            )
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

        # Code valide → persister le secret + activer la 2FA
        user.two_factor_secret = secret
        user.two_factor_enabled = True
        user.save(update_fields=["two_factor_secret", "two_factor_enabled"])

        # Nettoyer la session : secret consume + marquer la session comme verifiee
        request.session.pop(SETUP_SECRET_SESSION_KEY, None)
        request.session[VERIFIED_SESSION_KEY] = True
        # Empecher l'invalidation de la session apres un changement d'auth state
        update_session_auth_hash(request, user)

        log_action(
            user,
            "Activation de l'authentification a deux facteurs (TOTP)",
            request,
            niveau="INFO",
            objet_type="USER",
            objet_id=user.pk,
        )

        messages.success(
            request,
            "Authentification a deux facteurs activee avec succes.",
        )
        return redirect("accounts:profile")

    # GET : (re)generer un secret et afficher le QR
    secret = pyotp.random_base32()
    request.session[SETUP_SECRET_SESSION_KEY] = secret

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=user.email,
        issuer_name=TOTP_ISSUER,
    )
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


# ─── Vue 2 : Verify 2FA (post-login gate) ───────────────────────────────────


@require_http_methods(["GET", "POST"])
def verify_2fa(request):
    """
    Page de verification du code TOTP affichee APRES le login Django.

    L'utilisateur est deja authentifie (request.user.is_authenticated)
    mais sa session n'est pas encore marquee 2FA-validee. Le middleware
    TwoFactorMiddleware le redirige ici tant que `2fa_verified` n'est pas True.

    On NE met PAS @login_required car le middleware s'en charge en amont,
    mais on verifie quand meme is_authenticated par defense en profondeur.
    """
    user = request.user

    if not user.is_authenticated:
        return redirect("accounts:login")

    # Si 2FA pas activee, rien a verifier — eviter la boucle si on arrive ici
    # par hasard.
    if not getattr(user, "two_factor_enabled", False):
        request.session[VERIFIED_SESSION_KEY] = True
        return redirect("dashboard:index")

    # Deja verifie → continuer normalement
    if request.session.get(VERIFIED_SESSION_KEY):
        return redirect("dashboard:index")

    if request.method == "POST":
        token = _normalize_token(request.POST.get("token", ""))
        attempts = int(request.session.get(ATTEMPTS_SESSION_KEY, 0))

        if attempts >= MAX_VERIFY_ATTEMPTS:
            from django.contrib.auth import logout

            log_action(
                user,
                "CRITIQUE: 2FA verification - depassement du nombre de tentatives",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.pk,
            )
            logout(request)
            messages.error(
                request,
                "Trop de tentatives invalides. Vous avez ete deconnecte.",
            )
            return redirect("accounts:login")

        if not token or len(token) != 6:
            request.session[ATTEMPTS_SESSION_KEY] = attempts + 1
            messages.error(request, "Code invalide.")
            return render(request, "accounts/verify_2fa.html", status=400)

        totp = pyotp.TOTP(user.two_factor_secret)
        if not totp.verify(token, valid_window=1):
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

        # Succes
        request.session[VERIFIED_SESSION_KEY] = True
        request.session.pop(ATTEMPTS_SESSION_KEY, None)
        log_action(
            user,
            "2FA verification reussie",
            request,
            niveau="INFO",
            objet_type="USER",
            objet_id=user.pk,
        )
        return redirect("dashboard:index")

    return render(request, "accounts/verify_2fa.html")


# ─── Vue 3 : Disable 2FA ────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def disable_2fa(request):
    """
    Desactive la 2FA apres confirmation par mot de passe.

    Le mot de passe est demande pour eviter qu'une session vole/oubliee
    puisse desactiver la 2FA en un clic.
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

        user.two_factor_secret = ""
        user.two_factor_enabled = False
        user.save(update_fields=["two_factor_secret", "two_factor_enabled"])

        # La session reste valide mais le flag 2fa_verified n'est plus exige
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
