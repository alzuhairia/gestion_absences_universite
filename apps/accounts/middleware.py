# apps/accounts/middleware.py
import time
from functools import lru_cache

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse


@lru_cache(maxsize=1)
def _resolve_excluded_paths():
    """Resolve URL names to paths once (cached after first call)."""
    _excluded_url_names = [
        "accounts:password_change",
        "accounts:password_change_done",
        "accounts:password_reset",
        "accounts:password_reset_done",
        "accounts:password_reset_complete",
        "accounts:logout",
        "accounts:login",
    ]
    paths = []
    for name in _excluded_url_names:
        try:
            paths.append(reverse(name))
        except Exception:
            pass
    # Health endpoint and initial setup have no named URL in accounts
    paths.append("/api/health/")
    paths.append("/setup/")
    return tuple(paths)


class SessionInactivityMiddleware:
    """Log out users who have been inactive longer than SESSION_INACTIVITY_TIMEOUT."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.timeout = getattr(settings, "SESSION_INACTIVITY_TIMEOUT", 900)

    def __call__(self, request):
        if request.user.is_authenticated:
            now = time.time()
            last_activity = request.session.get("_last_activity")

            if last_activity is not None and (now - last_activity) > self.timeout:
                logout(request)
                messages.warning(
                    request,
                    "Votre session a expiré pour cause d'inactivité. "
                    "Veuillez vous reconnecter.",
                )
                return redirect(settings.LOGIN_URL)

            request.session["_last_activity"] = now

        return self.get_response(request)


class RoleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Vérifier les permissions par rôle si l'utilisateur est authentifié
        if request.user.is_authenticated:
            user = request.user
            path = request.path_info

            # Vérifier si l'utilisateur doit changer son mot de passe
            excluded_paths = _resolve_excluded_paths()
            is_excluded = any(path.startswith(excluded) for excluded in excluded_paths)

            if (
                not is_excluded
                and hasattr(user, "must_change_password")
                and user.must_change_password
            ):
                messages.warning(
                    request, "Vous devez changer votre mot de passe avant de continuer."
                )
                return redirect("accounts:password_change")

            # Règles d'accès par rôle
            try:
                admin_prefix = reverse("admin:index")
            except NoReverseMatch:
                admin_prefix = "/admin/"
            if path.startswith(admin_prefix) and not request.user.is_superuser:
                messages.error(request, "Accès non autorisé à l'administration.")
                return redirect("dashboard:index")

        return None
