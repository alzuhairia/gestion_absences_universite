"""
Vues de gestion de la sécurité administrateur pour le tableau de bord UniAbsences.

Vues
-----
``admin_user_reset_password``
    Génère un nouveau mot de passe aléatoire pour un compte utilisateur, définit
    ``must_change_password = True`` et affiche le mot de passe temporaire
    une seule fois (il n'est jamais stocké en clair après cette page).

``admin_user_reset_2fa``
    Désactive la 2FA TOTP pour un compte utilisateur et supprime ses codes de secours,
    permettant à l'utilisateur de se réinscrire à la prochaine connexion.

Fait partie du tableau de bord UniAbsences.
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods

from apps.accounts.models import TwoFactorBackupCode, User
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_user_reset_password(request, user_id):
    """Réinitialisation du mot de passe d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    new_password = (request.POST.get("new_password") or "").strip()
    if not new_password:
        messages.error(request, "Le mot de passe ne peut pas être vide.")
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    try:
        validate_password(new_password, user=user)
    except ValidationError as exc:
        for error in exc.messages:
            messages.error(request, error)
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    with transaction.atomic():
        user.set_password(new_password)
        user.must_change_password = True
        user.save(update_fields=["password", "must_change_password"])
        log_action(
            request.user,
            f"CRITIQUE: Réinitialisation du mot de passe pour '{user.email}' (Gestion des utilisateurs - Action de sécurité)",
            request,
            niveau="CRITIQUE",
            objet_type="USER",
            objet_id=user.id_utilisateur,
        )
    messages.success(
        request,
        f"Mot de passe réinitialisé pour '{user.email}'. L'utilisateur devra le changer lors de sa prochaine connexion.",
    )

    return redirect("dashboard:admin_user_edit", user_id=user_id)


@login_required
@admin_required
@require_http_methods(["POST"])
def admin_user_reset_2fa(request, user_id):
    """
    Réinitialise la 2FA d'un utilisateur (cas : perte du téléphone).

    Cette action :
      - désactive la 2FA (two_factor_enabled=False)
      - efface le secret TOTP
      - supprime tous les codes de secours existants

    L'utilisateur pourra se reconnecter avec son seul mot de passe puis
    réactiver la 2FA depuis son profil s'il le souhaite.

    Action CRITIQUE — journalisée dans l'audit.
    """
    user = get_object_or_404(User, id_utilisateur=user_id)

    if not user.two_factor_enabled and not TwoFactorBackupCode.objects.filter(
        user=user
    ).exists():
        messages.info(
            request,
            f"L'utilisateur '{user.email}' n'a pas la 2FA activée.",
        )
        return redirect("dashboard:admin_user_edit", user_id=user_id)

    with transaction.atomic():
        user.two_factor_enabled = False
        user.two_factor_secret = ""
        user.save(update_fields=["two_factor_enabled", "two_factor_secret"])
        TwoFactorBackupCode.objects.filter(user=user).delete()

        log_action(
            request.user,
            f"CRITIQUE: Réinitialisation 2FA pour '{user.email}' "
            f"(Gestion des utilisateurs - Perte téléphone / action admin)",
            request,
            niveau="CRITIQUE",
            objet_type="USER",
            objet_id=user.id_utilisateur,
        )

    messages.success(
        request,
        f"2FA réinitialisée pour '{user.email}'. "
        "L'utilisateur pourra se connecter avec son mot de passe seul.",
    )
    return redirect("dashboard:admin_user_edit", user_id=user_id)
