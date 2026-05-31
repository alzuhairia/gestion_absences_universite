"""
Vues d'authentification pour le système de comptes UniAbsences.

Ce module contient toutes les vues liées à l'authentification utilisateur
et à la gestion du mot de passe, avec rate limiting appliqué au niveau de
la vue via django-ratelimit.

Vues
----
``RateLimitedLoginView``
    Étend la ``LoginView`` de Django avec deux décorateurs de rate limiting
    empilés (par IP et par combinaison IP+username) pour atténuer les
    attaques par force brute et credential stuffing. Lors d'une connexion
    réussie elle :
      1. Crée un enregistrement ``UserSession`` pour la nouvelle session.
      2. Évince les enregistrements ``UserSession`` les plus anciens (plus
         les lignes Django ``Session`` correspondantes) lorsque la limite
         de sessions par utilisateur est dépassée.
      3. Redirige les utilisateurs 2FA activés vers la page de vérification
         TOTP plutôt que vers la destination post-login habituelle.

``CustomPasswordResetView``
    Étend la ``PasswordResetView`` de Django avec un rate limit par IP de
    5 par heure sur les demandes d'email de réinitialisation de mot de
    passe pour empêcher les attaques par email flooding.

``CustomPasswordResetConfirmView``
    Étend la ``PasswordResetConfirmView`` de Django ; rejette le lien de
    réinitialisation si le compte utilisateur est désactivé (``actif = False``) ;
    injecte également les indications de complexité de mot de passe
    ``SystemSettings`` dans le contexte du template afin que le front-end
    puisse afficher un indicateur de force interactif.

``CustomPasswordChangeView``
    Étend la ``PasswordChangeView`` de Django ; efface le drapeau
    ``must_change_password`` dans une transaction atomique après un
    changement réussi et redirige vers le tableau de bord approprié au rôle.

Fait partie du système de comptes UniAbsences.
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


# ---------------------------------------------------------------------------
# Deux décorateurs de rate limiting sont empilés sur ``dispatch`` afin que
# LES DEUX limites doivent passer avant qu'un POST ne soit traité :
#   1. Par IP  : configuré par LOGIN_RATE_LIMIT_IP dans les settings (par ex. "10/m").
#   2. Par IP+username : LOGIN_RATE_LIMIT_COMBINED (par ex. "5/m") pour ralentir
#      les attaques ciblées contre un compte spécifique depuis un pool d'IP rotatif.
# Aucun décorateur n'utilise ``block=True`` ; à la place, ``dispatch`` inspecte
# ``request.limited`` et retourne une réponse 429 avec un header Retry-After.
# ---------------------------------------------------------------------------
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
    """
    Vue de connexion avec rate limiting par IP et par IP+username.

    Étend la ``LoginView`` de Django avec :
    - Deux décorateurs de rate limiting en couches (voir commentaire au niveau du module ci-dessus).
    - Une surcharge de ``dispatch`` qui retourne HTTP 429 avec un header
      ``Retry-After`` lorsque l'un ou l'autre des rate limits se déclenche.
    - Une surcharge de ``form_valid`` qui applique la limite de sessions par
      utilisateur et route les utilisateurs 2FA activés vers la page de
      vérification TOTP.
    """

    template_name = "accounts/login.html"
    # Les utilisateurs authentifiés sont immédiatement renvoyés vers leur tableau de bord.
    redirect_authenticated_user = True
    authentication_form = CustomAuthenticationForm

    def dispatch(self, request, *args, **kwargs):
        """
        Intercepte la requête avant qu'elle n'atteigne la logique de traitement du formulaire.

        Lorsque l'un ou l'autre décorateur de rate limit a positionné
        ``request.limited = True``, la tentative de connexion est rejetée
        avec HTTP 429 et un header ``Retry-After: 300``. Le formulaire est
        tout de même rendu afin que l'utilisateur voie un message d'erreur
        informatif plutôt qu'une page blanche.

        Parameters:
            request: La requête HTTP entrante.
            *args: Arguments positionnels transmis au dispatcher parent.
            **kwargs: Arguments nommés transmis au dispatcher parent.

        Returns:
            HttpResponse: Soit une réponse 429 (rate limited) soit le résultat
                          du ``dispatch`` parent (flux normal).
        """
        # django-ratelimit positionne request.limited = True lorsqu'un seuil est atteint.
        if getattr(request, "limited", False):
            messages.error(
                request,
                "Trop de tentatives de connexion. Reessayez dans quelques minutes.",
            )
            response = self.render_to_response(
                self.get_context_data(form=self.get_form()), status=429
            )
            # Informe les clients (et les proxys intermédiaires) combien de temps attendre.
            response["Retry-After"] = "300"
            return response
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """
        Gère une connexion réussie : crée un enregistrement de session et applique la limite.

        Étapes effectuées dans une seule transaction de base de données :
        1. Appelle le ``form_valid`` parent qui appelle ``auth.login`` et
           crée la session Django.
        2. Insère une nouvelle ligne ``UserSession`` avec la clé de session,
           l'adresse IP et la chaîne user-agent tronquée.
        3. Récupère toutes les lignes ``UserSession`` pour cet utilisateur
           triées du plus récent au plus ancien.
        4. Évince toutes les lignes au-delà de ``MAX_SESSIONS_PER_USER`` —
           les enregistrements ``UserSession`` et les lignes Django
           ``Session`` sous-jacentes sont supprimés pour que les données
           obsolètes ne s'accumulent pas.

        Après l'entretien des sessions :
        - Si l'utilisateur a la 2FA activée, la clé ``2fa_verified`` est
          retirée de la session et l'utilisateur est redirigé vers ``verify_2fa``.
        - Sinon la redirection post-login normale se poursuit.

        Parameters:
            form: L'instance ``CustomAuthenticationForm`` validée.

        Returns:
            HttpResponse: Une redirection — soit vers la page de contrôle 2FA
                          soit vers la ``LOGIN_REDIRECT_URL`` standard.
        """
        # L'appel parent exécute auth.login(), positionnant request.user et la session.
        response = super().form_valid(form)
        user = self.request.user

        try:
            with transaction.atomic():
                # Enregistrer cette connexion dans la table d'audit des sessions.
                UserSession.objects.create(
                    user=user,
                    session_key=self.request.session.session_key,
                    ip_address=extract_client_ip(self.request),
                    # Tronquer à 500 caractères pour rester dans la limite de la colonne BDD.
                    user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:500],
                )

                # Récupérer toutes les sessions pour cet utilisateur, plus récente en premier.
                active_sessions = (
                    UserSession.objects.filter(user=user)
                    .order_by("-created_at")
                    .values_list("pk", "session_key", flat=False)
                )
                # Les sessions au-delà de la limite sont les plus anciennes (la queue du
                # queryset trié plus récent en premier).
                to_evict = list(active_sessions[UserSession.MAX_SESSIONS_PER_USER:])
                if to_evict:
                    evict_pks = [pk for pk, _ in to_evict]
                    evict_keys = [key for _, key in to_evict if key]
                    # Supprimer les données de session Django sous-jacentes en premier
                    # pour éviter les enregistrements de session orphelins.
                    if evict_keys:
                        Session.objects.filter(session_key__in=evict_keys).delete()
                    UserSession.objects.filter(pk__in=evict_pks).delete()
        except Exception:
            # Logguer mais ne pas annuler la connexion — la limite de sessions est best-effort.
            logger.exception("Failed to enforce session limit for user %s", user.pk)

        if getattr(user, "two_factor_enabled", False):
            # Retirer tout drapeau de vérification 2FA obsolète d'une session précédente
            # afin que l'utilisateur soit forcé de passer par le contrôle TOTP pour cette nouvelle connexion.
            self.request.session.pop("2fa_verified", None)
            return redirect("accounts:verify_2fa")

        return response


# ---------------------------------------------------------------------------
# Rate limit de réinitialisation de mot de passe : 5 requêtes par heure par IP.
# ``block=False`` garde le contrôle dans notre surcharge ``dispatch`` afin que nous puissions
# afficher une erreur conviviale plutôt que de compter sur le 403 par défaut de django-ratelimit.
# ---------------------------------------------------------------------------
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
    """
    Vue de demande de réinitialisation de mot de passe avec rate limiting par IP (5/heure).

    Envoie un lien de réinitialisation à l'adresse email soumise si un compte
    actif correspondant existe. Le rate limit empêche l'endpoint d'être
    utilisé comme vecteur d'email flooding contre des adresses arbitraires.
    """

    template_name = "accounts/password_reset.html"
    email_template_name = "accounts/password_reset_email.html"
    html_email_template_name = "accounts/password_reset_email_html.html"
    subject_template_name = "accounts/password_reset_subject.txt"
    form_class = CustomPasswordResetForm
    success_url = "/accounts/password_reset/done/"

    def dispatch(self, request, *args, **kwargs):
        """
        Rejette les demandes de réinitialisation rate-limitées avec HTTP 429 et une erreur visible.

        Parameters:
            request: La requête HTTP entrante.
            *args: Arguments positionnels transmis au parent.
            **kwargs: Arguments nommés transmis au parent.

        Returns:
            HttpResponse: Une réponse 429 lorsque rate limitée, sinon le
                          résultat du ``dispatch`` parent.
        """
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
    """
    Vue de confirmation de réinitialisation de mot de passe avec un garde-fou compte actif supplémentaire.

    La ``PasswordResetConfirmView`` intégrée de Django invalide déjà le token
    après usage (le token est dérivé du hash du mot de passe, il change donc
    quand le mot de passe est réinitialisé). Cette sous-classe ajoute :

    - Une vérification ``actif`` dans ``dispatch`` : si le compte a été
      désactivé après l'envoi du lien de réinitialisation, ``self.validlink``
      est positionné à ``False`` afin que le template rende le message "lien invalide".
    - L'injection des règles de complexité de mot de passe ``SystemSettings``
      dans le contexte du template afin que le front-end puisse montrer un
      indicateur de force en temps réel.
    """

    template_name = "accounts/password_reset_confirm.html"
    form_class = CustomSetPasswordForm
    success_url = "/accounts/reset/done/"

    def dispatch(self, request, *args, **kwargs):
        """
        Vérifie le token de réinitialisation et contrôle que le compte est toujours actif.

        Le ``dispatch`` parent valide la paire uidb64/token et positionne
        ``self.user`` quand ils sont valides. Si ``self.user.actif`` vaut
        ``False`` le lien est traité comme invalide indépendamment du token.

        Parameters:
            request: La requête HTTP entrante.
            *args: Arguments positionnels (uidb64, token) capturés par l'URL.
            **kwargs: Arguments nommés transmis au parent.

        Returns:
            HttpResponse: Le formulaire de réinitialisation, ou la page de
                          lien invalide si le compte est désactivé ou si le
                          token est expiré.
        """
        response = super().dispatch(request, *args, **kwargs)
        user = getattr(self, "user", None)
        # Traiter un compte désactivé comme un lien invalide pour empêcher
        # les réinitialisations de mot de passe sur les comptes suspendus.
        if user is not None and not user.actif:
            self.validlink = False
            return self.render_to_response(self.get_context_data())
        return response

    def get_context_data(self, **kwargs):
        """
        Ajoute les règles de mot de passe ``SystemSettings`` au contexte du template.

        Le front-end utilise ces valeurs pour construire un indicateur de
        force de mot de passe en temps réel sans nécessiter un appel API séparé.

        Parameters:
            **kwargs: Arguments nommés supplémentaires fusionnés dans le dict de contexte.

        Returns:
            dict: Contexte de template incluant une clé ``password_settings``
                  avec les exigences de complexité courantes.
        """
        context = super().get_context_data(**kwargs)
        from apps.dashboard.models import SystemSettings

        pw_settings = SystemSettings.get_settings()
        # Exposer chaque règle de complexité comme booléen/int afin que le template
        # puisse construire une checklist dynamique de force de mot de passe.
        context["password_settings"] = {
            "min_length": pw_settings.password_min_length,
            "require_uppercase": pw_settings.password_require_uppercase,
            "require_lowercase": pw_settings.password_require_lowercase,
            "require_numbers": pw_settings.password_require_numbers,
            "require_special": pw_settings.password_require_special,
        }
        return context


class CustomPasswordChangeView(auth_views.PasswordChangeView):
    """
    Vue de changement de mot de passe authentifiée qui efface ``must_change_password``.

    Étend la ``PasswordChangeView`` de Django avec deux comportements :
    - Injecte les règles de complexité de mot de passe ``SystemSettings``
      dans le contexte du template (même pattern que ``CustomPasswordResetConfirmView``).
    - En cas de succès, efface le drapeau ``must_change_password`` dans une
      transaction atomique, appelle ``update_session_auth_hash`` pour garder
      la session valide, et redirige vers le tableau de bord approprié au rôle.
    """

    template_name = "accounts/password_change.html"
    form_class = CustomPasswordChangeForm

    def get_context_data(self, **kwargs):
        """
        Ajoute les règles de complexité de mot de passe ``SystemSettings`` au contexte du template.

        Parameters:
            **kwargs: Arguments nommés supplémentaires fusionnés dans le dict de contexte.

        Returns:
            dict: Contexte de template incluant une clé ``password_settings``.
        """
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
        """
        Sauvegarde le nouveau mot de passe, efface le drapeau de changement forcé et redirige.

        Toutes les écritures BDD ont lieu dans une seule transaction atomique :
        1. ``form.save()`` hash et persiste le nouveau mot de passe.
        2. Si ``must_change_password`` est défini, il est effacé afin que
           l'utilisateur puisse naviguer librement après ce changement.

        ``update_session_auth_hash`` est appelé après la transaction pour
        faire tourner le hash d'auth de la session, empêchant l'utilisateur
        d'être déconnecté par le changement de mot de passe.

        La cible de redirection est déterminée par le rôle de l'utilisateur
        afin que chaque persona atterrisse sur son propre tableau de bord.

        Parameters:
            form: L'instance ``CustomPasswordChangeForm`` validée.

        Returns:
            HttpResponse: Une redirection vers le tableau de bord approprié au
                          rôle, ou vers la page de login pour les types
                          d'utilisateur non reconnus.
        """
        from django.db import transaction
        from apps.accounts.models_user import User

        request_user = self.request.user

        with transaction.atomic():
            form.save()
            # Effacer le drapeau de changement forcé afin que RoleMiddleware
            # cesse de rediriger cet utilisateur vers la page de changement de mot de passe.
            if isinstance(request_user, User) and request_user.must_change_password:
                request_user.must_change_password = False
                request_user.save(update_fields=["must_change_password"])  # type: ignore[call-arg]

        # Faire tourner le hash d'auth de la session afin que l'utilisateur reste connecté malgré
        # le changement de mot de passe invalidant l'ancienne signature de session.
        update_session_auth_hash(self.request, form.user)

        messages.success(
            self.request,
            "Votre mot de passe a été modifié avec succès. Vous pouvez maintenant accéder à toutes les fonctionnalités.",
        )

        if not isinstance(request_user, User):
            return redirect("accounts:login")

        # Router chaque rôle vers son tableau de bord dédié.
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
