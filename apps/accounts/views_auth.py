"""
FICHIER : apps/accounts/views_auth.py
RESPONSABILITE : Authentification — Login (rate-limited), reset et changement de mot de passe
"""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.sessions.models import Session
from django.db import transaction
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit

from apps.accounts.forms import (
    CustomAuthenticationForm,
    CustomPasswordChangeForm,
    CustomPasswordResetForm,
    CustomSetPasswordForm,
)
from apps.accounts.models import UserSession
from apps.audits.ip_utils import (
    extract_client_ip,
    ratelimit_client_ip,
    ratelimit_login_ip_username,
)

logger = logging.getLogger(__name__)


@method_decorator(
    ratelimit(
        key=ratelimit_client_ip,
        rate=settings.LOGIN_RATE_LIMIT_IP,
        method="POST",
        block=False,
    ),
    name="dispatch",
)
@method_decorator(
    ratelimit(
        key=ratelimit_login_ip_username,
        rate=settings.LOGIN_RATE_LIMIT_COMBINED,
        method="POST",
        block=False,
    ),
    name="dispatch",
)
class RateLimitedLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    redirect_authenticated_user = True
    authentication_form = CustomAuthenticationForm

    def dispatch(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            messages.error(
                request,
                "Trop de tentatives de connexion. Reessayez dans quelques minutes.",
            )
            response = self.render_to_response(
                self.get_context_data(form=self.get_form()), status=429
            )
            response["Retry-After"] = "300"
            return response
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Authenticate, enforce max sessions per user, and register the new session."""
        response = super().form_valid(form)
        user = self.request.user

        try:
            with transaction.atomic():
                UserSession.objects.create(
                    user=user,
                    session_key=self.request.session.session_key,
                    ip_address=extract_client_ip(self.request),
                    user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:500],
                )

                active_sessions = (
                    UserSession.objects.filter(user=user)
                    .order_by("-created_at")
                    .values_list("pk", "session_key", flat=False)
                )
                to_evict = list(active_sessions[UserSession.MAX_SESSIONS_PER_USER:])
                if to_evict:
                    evict_pks = [pk for pk, _ in to_evict]
                    evict_keys = [key for _, key in to_evict if key]
                    if evict_keys:
                        Session.objects.filter(session_key__in=evict_keys).delete()
                    UserSession.objects.filter(pk__in=evict_pks).delete()
        except Exception:
            logger.exception("Failed to enforce session limit for user %s", user.pk)

        if getattr(user, "two_factor_enabled", False):
            self.request.session.pop("2fa_verified", None)
            return redirect("accounts:verify_2fa")

        return response


@method_decorator(
    ratelimit(
        key=ratelimit_client_ip,
        rate="5/h",
        method="POST",
        block=False,
    ),
    name="dispatch",
)
class CustomPasswordResetView(auth_views.PasswordResetView):
    """Vue de demande de réinitialisation du mot de passe avec rate limiting."""

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.html"
    html_email_template_name = "accounts/password_reset_email_html.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    form_class = CustomPasswordResetForm
    success_url = "/accounts/password_reset/done/"

    def dispatch(self, request, *args, **kwargs):
        if getattr(request, "limited", False):
            messages.error(
                request,
                "Trop de demandes de réinitialisation. Réessayez plus tard.",
            )
            return self.render_to_response(
                self.get_context_data(form=self.get_form()), status=429
            )
        return super().dispatch(request, *args, **kwargs)


class CustomPasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    """Vue de confirmation de réinitialisation avec formulaire personnalisé.

    Django's PasswordResetConfirmView already invalidates tokens after use
    (the token is derived from the password hash, so it changes when the
    password is reset). We add a check that the user is still active.
    """

    template_name = "accounts/password_reset_confirm.html"
    form_class = CustomSetPasswordForm
    success_url = "/accounts/reset/done/"

    def dispatch(self, request, *args, **kwargs):
        response = super().dispatch(request, *args, **kwargs)
        user = getattr(self, "user", None)
        if user is not None and not user.actif:
            self.validlink = False
            return self.render_to_response(self.get_context_data())
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.dashboard.models import SystemSettings

        pw_settings = SystemSettings.get_settings()
        context["password_settings"] = {
            "min_length": pw_settings.password_min_length,
            "require_uppercase": pw_settings.password_require_uppercase,
            "require_lowercase": pw_settings.password_require_lowercase,
            "require_numbers": pw_settings.password_require_numbers,
            "require_special": pw_settings.password_require_special,
        }
        return context


class CustomPasswordChangeView(auth_views.PasswordChangeView):
    """Vue personnalisée pour le changement de mot de passe qui désactive must_change_password"""

    template_name = "accounts/password_change.html"
    form_class = CustomPasswordChangeForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        from apps.dashboard.models import SystemSettings

        settings = SystemSettings.get_settings()
        context["password_settings"] = {
            "min_length": settings.password_min_length,
            "require_uppercase": settings.password_require_uppercase,
            "require_lowercase": settings.password_require_lowercase,
            "require_numbers": settings.password_require_numbers,
            "require_special": settings.password_require_special,
        }
        return context

    def form_valid(self, form):
        """Désactiver le flag must_change_password après un changement réussi et rediriger vers le dashboard"""
        from django.db import transaction
        from apps.accounts.models_user import User

        request_user = self.request.user

        with transaction.atomic():
            form.save()

            if isinstance(request_user, User) and request_user.must_change_password:
                request_user.must_change_password = False
                request_user.save(update_fields=["must_change_password"])  # type: ignore[call-arg]

        update_session_auth_hash(self.request, form.user)

        messages.success(
            self.request,
            "Votre mot de passe a été modifié avec succès. Vous pouvez maintenant accéder à toutes les fonctionnalités.",
        )

        if not isinstance(request_user, User):
            return redirect("accounts:login")

        if request_user.role == User.Role.ETUDIANT:
            return redirect("dashboard:student_dashboard")
        elif request_user.role == User.Role.PROFESSEUR:
            return redirect("dashboard:instructor_dashboard")
        elif request_user.role == User.Role.ADMIN:
            return redirect("dashboard:admin_dashboard")
        elif request_user.role == User.Role.SECRETAIRE:
            return redirect("dashboard:secretary_dashboard")
        else:
            return redirect("dashboard:index")
