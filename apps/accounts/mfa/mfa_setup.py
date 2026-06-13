"""
Vues d'activation et de désactivation 2FA pour le système MFA d'UniAbsences.

Ce module gère les deux opérations de cycle de vie pour l'authentification à
deux facteurs basée sur TOTP : son activation (``setup_2fa``) et sa
désactivation (``disable_2fa``).

Vues
----
``setup_2fa``
    Assistant d'activation en deux étapes.
    GET  — génère un secret TOTP aléatoire, le stocke temporairement dans la
           session (pas en base de données) et affiche un QR code que
           l'utilisateur doit scanner avec son application d'authentification.
    POST — vérifie le premier code TOTP produit par l'application. En cas de
           succès, persiste le secret en base, génère les codes de secours et
           redirige vers la page d'affichage unique des codes de secours.
    Le secret n'est volontairement pas persisté tant que l'utilisateur n'a
    pas prouvé qu'il peut produire un code valide — cela évite les comptes
    « à moitié configurés ».

``disable_2fa``
    Désactivation après confirmation du mot de passe.
    GET  — affiche le formulaire de confirmation du mot de passe.
    POST — valide le mot de passe, efface le secret TOTP et le drapeau
           ``two_factor_enabled``, supprime tous les codes de secours et
           redirige vers la page de profil.
    La confirmation du mot de passe empêche qu'une session détournée
    n'abaisse silencieusement la sécurité du compte.

Helpers
-------
``_role_base_template``
    Retourne le nom du template Jinja2/Django de base correspondant au rôle
    de l'utilisateur afin que chaque page 2FA hérite de la bonne sidebar.

Fait partie du système accounts / MFA d'UniAbsences.
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
    Retourne le nom du template de base adapté au rôle pour les pages 2FA.

    Chaque page 2FA doit étendre le bon layout de base afin de s'afficher
    dans la bonne sidebar (admin, secrétaire, professeur ou étudiant). Si
    l'objet utilisateur ne possède pas d'attribut ``Role`` (ex. lors de
    tests avec un utilisateur factice), le ``base.html`` générique est
    retourné comme repli sûr.

    Paramètres :
        user : l'instance ``User`` authentifiée (ou tout objet possédant
               les attributs ``role`` et ``Role``).

    Retour :
        str : le nom du template à passer comme ``base_template`` dans le contexte.
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
    Assistant d'activation TOTP en deux étapes.

    Étape 1 — Requête GET
        Un secret TOTP Base32 aléatoire de 32 caractères est généré avec
        ``pyotp.random_base32()`` et stocké temporairement dans la session
        sous ``SETUP_SECRET_SESSION_KEY``. Une URI de provisionnement et un
        data URI de QR code sont affichés afin que l'utilisateur puisse
        scanner le code avec son application d'authentification
        (Google Authenticator, Authy, etc.). Le secret **n'est pas** écrit
        en base à ce stade.

    Étape 2 — Requête POST
        L'utilisateur soumet le code TOTP à 6 chiffres affiché par son
        application. Le token soumis est normalisé (espaces / non-chiffres
        supprimés) et vérifié contre le secret stocké en session avec une
        fenêtre ±1 (tolérance de dérive d'horloge de ±30 s).

        En cas de succès (dans une seule transaction atomique) :
        1. Le secret est persisté dans ``user.two_factor_secret``.
        2. ``user.two_factor_enabled`` est mis à ``True``.
        3. Un nouveau lot de codes de secours est généré.
        4. Le secret de session est effacé, ``VERIFIED_SESSION_KEY`` est mis à
           ``True``, et les codes de secours en clair sont placés dans la
           session pour un affichage unique.
        5. Le hash d'authentification de session est tourné via
           ``update_session_auth_hash``.
        6. L'action est enregistrée dans le journal d'audit.

    Paramètres :
        request : la requête HTTP authentifiée (GET ou POST).

    Retour :
        HttpResponse : la page de configuration du QR code (GET), une
                       redirection vers le profil (déjà activé), ou une
                       redirection vers la page d'affichage des codes de
                       secours (activation réussie).
    """
    user = request.user

    # Si la 2FA est déjà active, il n'y a rien à configurer.
    if user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs est deja activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        # Récupère le secret provisoire stocké dans la session lors de l'étape GET.
        secret = request.session.get(SETUP_SECRET_SESSION_KEY)
        token = _normalize_token(request.POST.get("token", ""))

        if not secret:
            # Session expirée entre l'affichage du QR et la soumission du code.
            messages.error(request, "La session de configuration a expire. Reessayez.")
            return redirect("accounts:setup_2fa")

        if not token or len(token) != 6:
            messages.error(request, "Veuillez saisir un code a 6 chiffres.")
            return redirect("accounts:setup_2fa")

        totp = pyotp.TOTP(secret)
        # valid_window=1 autorise une tolérance de ±30 s pour la dérive
        # d'horloge entre le serveur et l'appareil d'authentification de l'utilisateur.
        if not totp.verify(token, valid_window=1):
            messages.error(
                request,
                "Code invalide. Verifiez l'heure de votre telephone et reessayez.",
            )
            return redirect("accounts:setup_2fa")

        # Persiste le secret et active la 2FA atomiquement pour qu'il n'y
        # ait pas d'état où le drapeau est posé mais le secret absent (ou l'inverse).
        with transaction.atomic():
            user.two_factor_secret = secret
            user.two_factor_enabled = True
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            new_codes = _generate_backup_codes(user)

        # Nettoie le secret provisoire de la session.
        request.session.pop(SETUP_SECRET_SESSION_KEY, None)
        # Marque cette session comme vérifiée 2FA pour que le middleware cesse de rediriger.
        request.session[VERIFIED_SESSION_KEY] = True
        # Stocke les codes en clair pour la page d'affichage unique des codes de secours.
        request.session[BACKUP_CODES_SESSION_KEY] = new_codes
        # Tourne le hash d'authentification de session pour garder la session
        # valide après ce changement à incidence sécurité.
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

    # GET — génère un nouveau secret provisoire et affiche le QR code.
    secret = pyotp.random_base32()
    # Stocke le secret dans la session afin qu'il puisse être vérifié au prochain POST.
    request.session[SETUP_SECRET_SESSION_KEY] = secret

    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name=TOTP_ISSUER)
    # Convertit l'URI de provisionnement en data URI base64 inline pour la balise <img>.
    qr_data_uri = _generate_qr_data_uri(provisioning_uri)

    return render(
        request,
        "accounts/setup_2fa.html",
        {
            "qr_data_uri": qr_data_uri,
            "secret": secret,           # affiché comme repli de saisie manuelle
            "issuer": TOTP_ISSUER,
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def disable_2fa(request):
    """
    Désactive la 2FA TOTP après confirmation du mot de passe courant par l'utilisateur.

    L'étape de confirmation du mot de passe empêche un attaquant disposant
    d'une session valide mais détournée (ex. navigateur laissé sans
    surveillance) d'abaisser silencieusement le niveau de sécurité du compte.

    GET
        Affiche le formulaire de confirmation.

    POST
        Valide le mot de passe soumis. En cas d'échec, journalise un événement
        d'audit WARNING et retourne le formulaire avec une erreur (HTTP 400)
        pour que le client puisse réessayer.

        En cas de succès (dans une seule transaction atomique) :
        1. ``user.two_factor_secret`` est effacé.
        2. ``user.two_factor_enabled`` est mis à ``False``.
        3. Tous les enregistrements ``TwoFactorBackupCode`` de l'utilisateur sont supprimés.
        4. ``VERIFIED_SESSION_KEY`` est retiré de la session.
        5. Le hash d'authentification de session est tourné via
           ``update_session_auth_hash``.
        6. L'action est enregistrée dans le journal d'audit en gravité WARNING.

    Paramètres :
        request : la requête HTTP authentifiée (GET ou POST).

    Retour :
        HttpResponse : le formulaire de confirmation, une redirection vers le
                       profil en cas de succès, ou une redirection vers le
                       profil si la 2FA n'est pas actuellement activée.
    """
    user = request.user

    # Garde : rien à désactiver si la 2FA n'est pas active.
    if not user.two_factor_enabled:
        messages.info(request, "L'authentification a deux facteurs n'est pas activee.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
            # Audite une tentative échouée — des échecs répétés peuvent
            # indiquer un attaquant cherchant à affaiblir la protection 2FA du compte.
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
            # Efface atomiquement tous les champs 2FA pour ne laisser aucun état semi-désactivé.
            user.two_factor_secret = ""
            user.two_factor_enabled = False
            user.save(update_fields=["two_factor_secret", "two_factor_enabled"])
            # Invalide tous les codes de secours — ils ne sont valides que tant que la 2FA est active.
            TwoFactorBackupCode.objects.filter(user=user).delete()

        # Retire le drapeau de vérification 2FA pour que le middleware reflète
        # immédiatement le nouvel état pour toute requête ultérieure dans cette session.
        request.session.pop(VERIFIED_SESSION_KEY, None)
        # Tourne le hash d'authentification de session après ce changement à incidence sécurité.
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
