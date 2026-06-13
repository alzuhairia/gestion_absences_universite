"""
Vues de gestion des codes de secours pour le système MFA d'UniAbsences.

Ce module gère les deux vues côté utilisateur liées aux codes de secours
TOTP : la page d'affichage unique présentée juste après la génération des
codes, et le flux de régénération qui permet aux utilisateurs d'invalider
tous les codes existants et d'en émettre un nouveau lot après confirmation
de leur mot de passe.

Vues
----
``backup_codes_view``
    GET uniquement. Lit les codes en clair nouvellement générés depuis la
    session (placés là par ``setup_2fa`` ou ``regenerate_backup_codes``), les
    formate pour l'affichage, efface immédiatement la clé de session et
    affiche le template. Si la clé de session est absente, l'utilisateur
    est redirigé vers son profil — les codes ne sont volontairement pas
    stockés et ne peuvent pas être récupérés.

``regenerate_backup_codes``
    GET  — affiche le formulaire de confirmation (saisie du mot de passe requise).
    POST — valide le mot de passe, génère un nouveau lot de codes
           atomiquement, stocke les codes en clair dans la session et
           redirige vers ``backup_codes_view`` pour un affichage unique.

Fait partie du système accounts / MFA d'UniAbsences.
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
    Affiche les codes de secours nouvellement générés exactement une fois.

    Cette vue est la page d'arrivée après la configuration 2FA ou la
    régénération des codes. Les codes en clair sont stockés dans la session
    sous ``BACKUP_CODES_SESSION_KEY`` par la vue amont, récupérés ici,
    formatés pour l'affichage, puis immédiatement retirés de la session pour
    qu'ils ne puissent pas être revus lors d'un rafraîchissement de la page
    ou d'une visite ultérieure.

    Si la clé de session est absente (l'utilisateur a navigué directement
    ou a déjà consulté les codes), un avertissement est affiché et
    l'utilisateur est redirigé vers sa page de profil avec des instructions
    pour régénérer les codes si nécessaire.

    Accessible uniquement lorsque le compte de l'utilisateur a déjà la 2FA
    activée — se prémunit contre un accès direct par URL avant que la
    configuration 2FA ne soit complète.

    Paramètres :
        request : la requête GET authentifiée.

    Retour :
        HttpResponse : le template ``accounts/backup_codes.html`` rendu avec
                       les codes formatés, ou une redirection vers le profil.
    """
    user = request.user

    # Garde : doit avoir la 2FA activée pour consulter les codes de secours.
    if not user.two_factor_enabled:
        return redirect("accounts:profile")

    raw_codes = request.session.get(BACKUP_CODES_SESSION_KEY)
    if not raw_codes:
        # Les codes ont déjà été consultés ou n'ont jamais été stockés (accès direct par URL).
        messages.info(
            request,
            "Les codes de secours ne peuvent etre affiches qu'une seule fois "
            "apres generation. Regenerez-les si vous les avez perdus.",
        )
        return redirect("accounts:profile")

    # Retire les codes de la session immédiatement pour qu'ils ne puissent pas être revisités.
    request.session.pop(BACKUP_CODES_SESSION_KEY, None)

    # Formate chaque code brut de 10 caractères en « XXXXX-XXXXX » pour la lisibilité.
    formatted = [_format_backup_code(c) for c in raw_codes]

    return render(
        request,
        "accounts/backup_codes.html",
        {
            "codes": formatted,
            # Transmet le template de base adapté au rôle pour que la page
            # hérite de la bonne sidebar et du bon layout de navigation.
            "base_template": _role_base_template(user),
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def regenerate_backup_codes(request):
    """
    Régénère tous les codes de secours après confirmation du mot de passe.

    Cette vue est une opération sensible à la sécurité : générer un nouveau
    lot invalide immédiatement **tous** les codes de secours existants
    (utilisés ou non). La confirmation du mot de passe est requise pour
    empêcher un attaquant disposant d'une session authentifiée détournée
    d'invalider silencieusement les codes de récupération de l'utilisateur.

    GET
        Affiche le formulaire de confirmation du mot de passe.

    POST
        Valide le mot de passe soumis. En cas d'échec, journalise la
        tentative en gravité WARNING et retourne le formulaire avec une
        erreur (HTTP 400). En cas de succès, génère un nouveau lot de codes
        de secours, stocke les codes en clair dans la session pour un
        affichage unique, journalise l'action et redirige vers
        ``backup_codes_view``.

    Paramètres :
        request : la requête HTTP authentifiée (GET ou POST).

    Retour :
        HttpResponse : le formulaire de confirmation, une redirection vers
                       ``backup_codes_view`` en cas de succès, ou une
                       redirection vers le profil si la 2FA n'est pas activée.
    """
    user = request.user

    # Garde : la régénération n'a de sens que lorsque la 2FA est active.
    if not user.two_factor_enabled:
        messages.info(request, "Activez d'abord l'authentification a deux facteurs.")
        return redirect("accounts:profile")

    if request.method == "POST":
        password = request.POST.get("password", "")
        if not password or not user.check_password(password):
            # Journalise la tentative échouée pour la piste d'audit de sécurité.
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

        # Génère un nouveau lot — tous les codes existants sont supprimés atomiquement.
        new_codes = _generate_backup_codes(user)
        # Stocke les codes en clair dans la session pour un seul aller-retour d'affichage.
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
