# apps/accounts/middleware.py
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse


class RoleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self._excluded_url_names = [
            "accounts:password_change",
            "accounts:password_change_done",
            "accounts:logout",
            "accounts:login",
        ]

    def __call__(self, request):
        response = self.get_response(request)
        return response

    def _get_excluded_paths(self):
        """Resolve URL names to paths at runtime (after URL conf is loaded)."""
        paths = []
        for name in self._excluded_url_names:
            try:
                paths.append(reverse(name))
            except Exception:
                pass
        # Health endpoint has no named URL in accounts, keep as literal
        paths.append("/api/health/")
        return paths

    def process_view(self, request, view_func, view_args, view_kwargs):
        # Vérifier les permissions par rôle si l'utilisateur est authentifié
        if request.user.is_authenticated:
            user = request.user
            path = request.path_info

            # Vérifier si l'utilisateur doit changer son mot de passe
            excluded_paths = self._get_excluded_paths()
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
