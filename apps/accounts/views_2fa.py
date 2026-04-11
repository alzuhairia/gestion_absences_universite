"""
FICHIER : apps/accounts/views_2fa.py
RESPONSABILITE : Vues pour l'authentification a deux facteurs (TOTP)
FONCTIONNALITES PRINCIPALES :
  - setup_2fa : generation du secret + QR code, activation apres verification
  - verify_2fa : verification du code TOTP apres login (gate post-login)
  - disable_2fa : desactivation 2FA avec confirmation par mot de passe
  - backup_codes : generation + affichage one-shot des codes de secours
DEPENDANCES CLES : pyotp (TOTP), qrcode (PNG QR), apps.audits.utils.log_action
"""

import base64
import io
import logging
import secrets

import pyotp
import qrcode
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from apps.audits.utils import log_action

from .models import TwoFactorBackupCode

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

#: Cle de session ou sont stockes temporairement les codes de secours en clair
#: (le temps d'un aller-retour vers la page d'affichage one-shot).
BACKUP_CODES_SESSION_KEY = "_2fa_new_backup_codes"

#: Nombre de caracteres de chaque code de secours (5+5 = 10).
BACKUP_CODE_LENGTH = 10


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


# ─── Backup codes helpers ───────────────────────────────────────────────────


def _normalize_backup_code(raw: str) -> str:
    """Upper-case + keep only A-Z/0-9. Accepts 'ABCD-EFGH' or 'abcdefgh'."""
    if not raw:
        return ""
    return "".join(ch for ch in raw.upper() if ch.isalnum())[: BACKUP_CODE_LENGTH]


def _format_backup_code(raw: str) -> str:
    """Format a raw 10-char code as 5-5 groups for display: ABCDE-FGHIJ."""
    mid = BACKUP_CODE_LENGTH // 2
    return f"{raw[:mid]}-{raw[mid:]}"


def _generate_backup_codes(user, nb=TwoFactorBackupCode.CODES_PER_BATCH):
    """
    Create `nb` backup codes for this user, replacing any existing ones.

    Returns the plaintext codes (list of str) so the caller can display
    them ONCE. Only hashes are persisted.
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # skip O/0/1/I
    plaintext = []
    with transaction.atomic():
        # Wipe any previous codes — generating new ones invalidates the old.
        TwoFactorBackupCode.objects.filter(user=user).delete()
        rows = []
        for _ in range(nb):
            raw = "".join(secrets.choice(alphabet) for _ in range(BACKUP_CODE_LENGTH))
            plaintext.append(raw)
            rows.append(
                TwoFactorBackupCode(
                    user=user,
                    code_hash=make_password(raw),
                )
            )
        TwoFactorBackupCode.objects.bulk_create(rows)
    return plaintext


def _consume_backup_code(user, candidate: str) -> bool:
    """
    Check a user-submitted backup code against this user's unused codes.
    Returns True (and marks the code used) on match, False otherwise.
    Constant-time over the set of unused codes.
    """
    if not candidate or len(candidate) != BACKUP_CODE_LENGTH:
        return False
    with transaction.atomic():
        unused = list(
            TwoFactorBackupCode.objects.select_for_update()
            .filter(user=user, used=False)
        )
        for row in unused:
            if check_password(candidate, row.code_hash):
                row.used = True
                row.used_at = timezone.now()
                row.save(update_fields=["used", "used_at"])
                return True
    return False


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

        # Code valide → persister le secret + activer la 2FA + generer codes de secours
        with transaction.atomic():
            user.two_factor_secret = secret
            user.two_factor_enabled = True
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            new_codes = _generate_backup_codes(user)

        # Nettoyer la session : secret consume + marquer la session comme verifiee
        request.session.pop(SETUP_SECRET_SESSION_KEY, None)
        request.session[VERIFIED_SESSION_KEY] = True
        # Stocker les codes en session pour affichage one-shot sur la page suivante.
        request.session[BACKUP_CODES_SESSION_KEY] = new_codes
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
        return redirect("accounts:backup_codes")

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
        raw_code = request.POST.get("token", "")
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

        # Try TOTP first (6 digits), then backup code.
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

        # Succes
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

        # Advertise low backup-code stock so the user regenerates
        if method_used == "BACKUP":
            remaining = TwoFactorBackupCode.objects.filter(
                user=user, used=False
            ).count()
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

        with transaction.atomic():
            user.two_factor_secret = ""
            user.two_factor_enabled = False
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            # Les codes de secours ne servent plus a rien sans 2FA active.
            TwoFactorBackupCode.objects.filter(user=user).delete()

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


# ─── Vue 4 : Affichage one-shot des codes de secours ────────────────────────


@login_required
@require_http_methods(["GET"])
def backup_codes_view(request):
    """
    Page affichee UNE SEULE FOIS apres:
      - l'activation de la 2FA (setup_2fa)
      - une regeneration (regenerate_backup_codes)

    Les codes en clair sont recuperes de la session puis la cle session est
    effacee immediatement apres le rendu — ils ne pourront plus etre revus.
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

    # Retirer immediatement de la session — visible une seule fois.
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


# ─── Vue 5 : Regeneration des codes de secours ──────────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def regenerate_backup_codes(request):
    """
    Regenere les codes de secours apres confirmation par mot de passe.
    Invalide immediatement TOUS les anciens codes (utilises ou non).
    """
    user = request.user
    if not user.two_factor_enabled:
        messages.info(
            request, "Activez d'abord l'authentification a deux facteurs."
        )
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
