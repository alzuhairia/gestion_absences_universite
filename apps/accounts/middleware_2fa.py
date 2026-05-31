"""
Middleware d'application de l'authentification à deux facteurs pour UniAbsences.

``TwoFactorMiddleware`` s'exécute à chaque requête et bloque l'accès aux pages
protégées pour les utilisateurs dont le compte a la 2FA TOTP activée mais qui
n'ont pas encore complété l'étape de vérification TOTP dans la session courante.

Flux d'authentification
-----------------------
1. L'utilisateur soumet son nom d'utilisateur + mot de passe à ``RateLimitedLoginView``.
   ``form_valid`` appelle l'``auth.login`` de Django, créant une session
   authentifiée standard, puis redirige vers ``accounts:verify_2fa``.
2. ``TwoFactorMiddleware.__call__`` détecte que ``VERIFIED_SESSION_KEY`` est
   absent et redirige toute URL non whitelistée vers ``verify_2fa``, empêchant
   ainsi l'utilisateur d'atteindre toute page protégée.
3. Une fois que l'utilisateur soumet un code TOTP ou un code de secours valide,
   ``verify_2fa`` inscrit ``VERIFIED_SESSION_KEY = True`` dans la session et
   le middleware cesse de rediriger.

La whitelist (login, logout, verify_2fa, flux de mot de passe, fichiers
statiques/media, health-check et URL dynamiques des tokens de réinitialisation)
est calculée une seule fois par démarrage de processus et mise en cache via
``lru_cache`` pour éviter les répétitions de résolution d'URL à chaque requête.

Fait partie du système de comptes UniAbsences.
"""

from functools import lru_cache

from django.conf import settings
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

from apps.accounts.mfa.mfa_service import VERIFIED_SESSION_KEY


@lru_cache(maxsize=1)
def _resolve_2fa_excluded_paths():
    """
    Calcule et met en cache l'ensemble des chemins URL exemptés du contrôle 2FA.

    Les chemins de cette liste sont autorisés à passer ``TwoFactorMiddleware``
    même lorsque la session de l'utilisateur n'a pas encore été marquée comme
    vérifiée 2FA. Cela évite les boucles de redirection et permet aux
    utilisateurs de compléter l'authentification, de récupérer un mot de passe
    oublié, ou de recevoir les réponses health-check.

    Catégories exemptées :
    - ``accounts:login`` / ``accounts:logout`` — sans ces URL l'utilisateur
      ne peut pas s'authentifier ou effacer sa session.
    - ``accounts:verify_2fa`` — la page de contrôle elle-même doit être accessible.
    - ``accounts:setup_2fa`` / ``accounts:disable_2fa`` — gestion de l'état 2FA.
    - Flux de réinitialisation de mot de passe — autoriser la récupération
      en libre-service sans 2FA.

    Les chemins dynamiques (par ex. ``/accounts/reset/<uidb64>/<token>/``) ne
    peuvent pas être résolus ici ; ils sont matchés par préfixe dans
    ``_is_request_exempt``.

    Returns:
        tuple[str, ...]: Chemins URL absolus résolus qui contournent le contrôle.
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
            # Ignorer les noms non enregistrés (par ex. fonctionnalité pas encore branchée).
            pass
    return tuple(paths)


class TwoFactorMiddleware:
    """
    Middleware de contrôle qui impose la vérification TOTP pour les comptes 2FA activés.

    Ce middleware doit apparaître **après** ``AuthenticationMiddleware`` dans
    le paramètre ``MIDDLEWARE`` afin que ``request.user`` soit peuplé avant
    l'exécution du contrôle 2FA.

    Pour toute requête provenant d'un utilisateur authentifié dont le compte
    a la 2FA activée et dont la session ne porte pas encore
    ``VERIFIED_SESSION_KEY``, le middleware retourne une redirection vers
    ``accounts:verify_2fa`` sans invoquer la vue en aval. Les chemins exemptés
    (voir ``_is_request_exempt``) sont laissés passer sans condition.
    """

    def __init__(self, get_response):
        """
        Stocke le callable middleware/vue suivant.

        Parameters:
            get_response: Le callable suivant dans la chaîne de middleware WSGI.
        """
        self.get_response = get_response

    def __call__(self, request):
        """
        Redirige les utilisateurs 2FA activés vers la page de vérification lorsque non vérifiés.

        Parameters:
            request: La requête HTTP entrante.

        Returns:
            HttpResponse: Une redirection vers ``accounts:verify_2fa`` si le
                          contrôle 2FA échoue, sinon la réponse du middleware
                          ou de la vue suivant.
        """
        if not self._is_request_exempt(request):
            user = getattr(request, "user", None)
            if (
                user is not None
                and user.is_authenticated
                and getattr(user, "two_factor_enabled", False)
                and not request.session.get(VERIFIED_SESSION_KEY)
            ):
                # L'utilisateur est connecté et a la 2FA activée mais n'a pas
                # encore complété l'étape de vérification TOTP pour cette session.
                return redirect("accounts:verify_2fa")
        return self.get_response(request)

    @staticmethod
    def _is_request_exempt(request) -> bool:
        """
        Détermine si cette requête doit contourner le contrôle 2FA.

        Une requête est exemptée lorsque son chemin appartient à l'une des
        catégories suivantes :
        - Fichiers statiques ou media (servis directement, aucune authentification requise).
        - L'endpoint de monitoring ``/api/health/``.
        - La page de configuration initiale ``/setup/``.
        - Une URL nommée dans la liste d'exemption mise en cache (login, logout, verify, etc.).
        - Une URL dynamique de token de réinitialisation (``/accounts/reset/<...>/``).

        Parameters:
            request: La requête HTTP entrante.

        Returns:
            bool: ``True`` si la requête doit ignorer le contrôle 2FA.
        """
        path = request.path_info

        # Les assets statiques et media sont servis sans contexte d'authentification.
        if path.startswith(getattr(settings, "STATIC_URL", "/static/")):
            return True
        if path.startswith(getattr(settings, "MEDIA_URL", "/media/") or "/media/"):
            return True

        # Endpoints d'infrastructure qui doivent toujours être accessibles.
        if path.startswith("/api/health/") or path.startswith("/setup/"):
            return True

        # URL d'authentification / 2FA nommées résolues une fois et mises en cache.
        if path in _resolve_2fa_excluded_paths():
            return True

        # Les URL de tokens de réinitialisation dynamiques contiennent un segment uidb64 et token
        # qui ne peut pas être préalablement résolu ; les matcher par préfixe à la place.
        if path.startswith("/accounts/reset/"):
            return True

        return False
