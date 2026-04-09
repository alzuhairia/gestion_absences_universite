"""
FICHIER : apps/accounts/middleware_2fa.py
RESPONSABILITE : Middleware d'application de la verification 2FA post-login
FONCTIONNALITES PRINCIPALES :
  - Bloque l'acces aux pages protegees tant que la session n'a pas valide
    le code TOTP de l'utilisateur (si la 2FA est activee sur le compte)
  - Whitelist : login, logout, verify_2fa, statiques, healthcheck
DEPENDANCES CLES : apps.accounts.views_2fa.VERIFIED_SESSION_KEY
"""

from functools import lru_cache

from django.conf import settings
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

from apps.accounts.views_2fa import VERIFIED_SESSION_KEY


@lru_cache(maxsize=1)
def _resolve_2fa_excluded_paths():
    """
    Liste des chemins qui ne doivent JAMAIS rediriger vers verify_2fa.

    On exclut explicitement :
    - login / logout : sinon impossible de se reconnecter
    - verify_2fa : sinon boucle de redirection
    - password_reset / password_change : permettre la recuperation
    - healthcheck : monitoring externe (Uptime Kuma)
    """
    names = [
        "accounts:login",
        "accounts:logout",
        "accounts:verify_2fa",
        "accounts:setup_2fa",
        "accounts:disable_2fa",
        "accounts:password_reset",
        "accounts:password_reset_done",
        "accounts:password_reset_complete",
    ]
    paths = []
    for name in names:
        try:
            paths.append(reverse(name))
        except NoReverseMatch:
            pass
    return tuple(paths)


class TwoFactorMiddleware:
    """
    Si l'utilisateur a active la 2FA et que sa session n'a PAS encore valide
    le code TOTP, le rediriger vers la page de verification.

    Place APRES `AuthenticationMiddleware` dans `MIDDLEWARE` pour avoir acces
    a `request.user`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not self._is_request_exempt(request):
            user = getattr(request, "user", None)
            if (
                user is not None
                and user.is_authenticated
                and getattr(user, "two_factor_enabled", False)
                and not request.session.get(VERIFIED_SESSION_KEY)
            ):
                return redirect("accounts:verify_2fa")
        return self.get_response(request)

    @staticmethod
    def _is_request_exempt(request) -> bool:
        path = request.path_info

        # Statiques et media
        if path.startswith(getattr(settings, "STATIC_URL", "/static/")):
            return True
        if path.startswith(getattr(settings, "MEDIA_URL", "/media/") or "/media/"):
            return True

        # URLs systeme
        if path.startswith("/api/health/") or path.startswith("/setup/"):
            return True

        # Routes auth resolues une fois et mises en cache
        if path in _resolve_2fa_excluded_paths():
            return True

        # Reset password tokens (path dynamique avec uidb64/token)
        if path.startswith("/accounts/reset/"):
            return True

        return False
