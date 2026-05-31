"""
Middleware de sécurité pour le système de comptes UniAbsences.

Ce module fournit deux classes de middleware WSGI exécutées à chaque requête
afin d'appliquer l'hygiène des sessions et les règles d'accès basées sur les rôles.

``SessionInactivityMiddleware``
    Déconnecte les utilisateurs authentifiés restés inactifs plus longtemps que
    ``settings.SESSION_INACTIVITY_TIMEOUT`` secondes (par défaut 15 minutes /
    900 s). Chaque requête non liée à la déconnexion rafraîchit un horodatage
    d'activité stocké dans la session sous ``_last_activity``, de sorte que
    seules les sessions véritablement inactives sont terminées.

``RoleMiddleware``
    Applique deux contrôles d'accès au niveau applicatif après authentification :
    1. Les utilisateurs avec ``must_change_password = True`` sont redirigés vers
       la page de changement de mot de passe à chaque requête, jusqu'à ce que
       le drapeau soit effacé.
    2. Les comptes non superuser / non staff qui tentent d'accéder au site
       d'administration Django (tout chemin commençant par ``/admin/``) sont
       redirigés vers le tableau de bord principal avec un message d'erreur.

Les deux classes suivent l'API de middleware Django ``__init__`` / ``__call__``.
``RoleMiddleware`` implémente également ``process_view`` pour les contrôles
d'accès qui nécessitent la connaissance de la fonction de vue correspondante.

Fait partie du système de comptes UniAbsences.
"""

import logging
import time
from functools import lru_cache

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import NoReverseMatch, reverse

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _resolve_excluded_paths():
    """
    Résout les patterns d'URL nommés en chemins concrets et met en cache le résultat.

    Le tuple retourné contient tous les chemins de requête que
    ``RoleMiddleware`` doit ignorer lors de l'application de la redirection
    ``must_change_password``. Ce sont les chemins que l'utilisateur doit
    pouvoir atteindre même lorsqu'un changement de mot de passe forcé est
    en attente (par ex. le formulaire de changement lui-même, login, logout,
    réinitialisation de mot de passe, et l'endpoint health-check).

    ``lru_cache(maxsize=1)`` garantit que la résolution d'URL n'est effectuée
    qu'une seule fois durant la vie du processus — les appels suivants
    retournent le tuple mis en cache à un coût pratiquement nul.

    Returns:
        tuple[str, ...]: Chemins URL absolus exemptés de la vérification
                         ``must_change_password``.
    """
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
            # Ignore silencieusement tout nom d'URL non encore enregistré
            # (par ex. lors du démarrage avant le chargement de la conf URL).
            pass
    # L'endpoint de santé et la page de configuration initiale ne sont pas
    # enregistrés sous le namespace accounts mais doivent toujours être accessibles.
    paths.append("/api/health/")
    paths.append("/setup/")
    return tuple(paths)


class SessionInactivityMiddleware:
    """
    Termine les sessions inactives pour réduire la surface d'attaque des navigateurs abandonnés.

    À chaque requête provenant d'un utilisateur authentifié, le middleware
    vérifie combien de temps s'est écoulé depuis sa dernière interaction
    avec l'application. Si l'écart dépasse ``SESSION_INACTIVITY_TIMEOUT``,
    l'utilisateur est déconnecté et un avertissement lui est présenté.
    L'horodatage est rafraîchi à chaque requête non évincée.

    Le délai d'inactivité vaut 900 secondes (15 minutes) par défaut lorsque le
    paramètre est absent. Définir ``SESSION_INACTIVITY_TIMEOUT = 0`` dans les
    settings désactive entièrement l'éviction par inactivité (la vérification
    ``> self.timeout`` ne se déclenchera jamais).
    """

    def __init__(self, get_response):
        """
        Stocke le callable middleware/vue suivant et lit le paramètre de timeout.

        Parameters:
            get_response: Le callable suivant dans la chaîne de middleware
                          (une vue ou le middleware suivant).
        """
        self.get_response = get_response
        # Valeur par défaut de 900 s (15 min) si le paramètre n'est pas défini.
        self.timeout = getattr(settings, "SESSION_INACTIVITY_TIMEOUT", 900)

    def __call__(self, request):
        """
        Vérifie l'inactivité, déconnecte si expirée, puis rafraîchit l'horodatage.

        Parameters:
            request: La requête HTTP entrante.

        Returns:
            HttpResponse: Une redirection vers ``settings.LOGIN_URL`` lorsque
                          la session a expiré, sinon la réponse produite par
                          le middleware/vue suivant.
        """
        try:
            if request.user.is_authenticated:
                now = time.time()
                last_activity = request.session.get("_last_activity")

                # Appliquer le timeout uniquement quand un horodatage précédent existe.
                # La toute première requête après login n'a pas encore d'horodatage.
                if last_activity is not None and (now - last_activity) > self.timeout:
                    logout(request)
                    messages.warning(
                        request,
                        "Votre session a expiré pour cause d'inactivité. "
                        "Veuillez vous reconnecter.",
                    )
                    return redirect(settings.LOGIN_URL)

                # Rafraîchir l'horodatage d'activité pour que les utilisateurs actifs ne soient jamais évincés.
                request.session["_last_activity"] = now
        except Exception:
            # Ne pas faire planter l'application si le backend de session est indisponible ;
            # logguer l'exception pour le monitoring et laisser la requête se poursuivre.
            logger.exception("SessionInactivityMiddleware error (session backend may be down)")

        return self.get_response(request)


class RoleMiddleware:
    """
    Applique les règles d'accès basées sur les rôles à chaque requête authentifiée.

    Deux règles sont appliquées dans ``process_view`` :

    1. **Changement de mot de passe forcé** — si ``user.must_change_password``
       est défini et que le chemin de la requête ne figure pas dans la liste
       d'exemption, l'utilisateur est redirigé vers ``accounts:password_change``
       quelle que soit l'URL initialement demandée.

    2. **Protection de la zone d'administration** — seuls les superusers
       (rôle ADMIN) peuvent atteindre toute URL dont le chemin commence par
       le préfixe admin Django. Le personnel non superuser (SECRETAIRE) et
       les utilisateurs réguliers sont redirigés vers le tableau de bord.

    Note : ``__call__`` délègue simplement à ``get_response`` ; la logique
    d'accès se trouve dans ``process_view`` qui est invoquée par la machinerie
    de middleware Django *après* la résolution d'URL mais *avant* l'appel de la vue.
    """

    def __init__(self, get_response):
        """
        Stocke le callable middleware/vue suivant.

        Parameters:
            get_response: Le callable suivant dans la chaîne de middleware.
        """
        self.get_response = get_response

    def __call__(self, request):
        """
        Transmet la requête au middleware/vue suivant sans modification.

        Toute la logique d'accès est gérée dans ``process_view``.

        Parameters:
            request: La requête HTTP entrante.

        Returns:
            HttpResponse: La réponse du middleware ou de la vue suivant.
        """
        response = self.get_response(request)
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        """
        Applique les règles d'accès basées sur les rôles avant l'exécution de la vue.

        Appelée par Django après la résolution d'URL. Retourne ``None`` pour
        laisser la requête se poursuivre normalement, ou une ``HttpResponse``
        de redirection pour bloquer l'accès.

        Parameters:
            request: La requête HTTP entrante (avec ``request.user`` défini).
            view_func: Le callable de vue qui traiterait cette requête.
            view_args: Arguments positionnels capturés depuis le pattern d'URL.
            view_kwargs: Arguments nommés capturés depuis le pattern d'URL.

        Returns:
            HttpResponse | None: Une redirection si une règle d'accès se
                                 déclenche, ou ``None`` pour laisser la vue
                                 s'exécuter.
        """
        if request.user.is_authenticated:
            user = request.user
            path = request.path_info

            # Résoudre la liste d'exemption une fois ; les appels suivants utilisent le cache.
            excluded_paths = _resolve_excluded_paths()
            is_excluded = path in excluded_paths

            from apps.accounts.models import User

            # Règle 1 : redirection vers la page de changement de mot de passe si le drapeau est défini
            # et que le chemin courant n'est pas dans la liste d'exemption.
            if not is_excluded and isinstance(user, User) and user.must_change_password:
                messages.warning(
                    request, "Vous devez changer votre mot de passe avant de continuer."
                )
                return redirect("accounts:password_change")

            # Règle 2 : seuls les superusers peuvent accéder à la zone d'administration Django.
            try:
                admin_prefix = reverse("admin:index")
            except NoReverseMatch:
                # Solution de repli si l'app admin n'est pas installée.
                admin_prefix = "/admin/"
            if path.startswith(admin_prefix) and not request.user.is_superuser:
                messages.error(request, "Accès non autorisé à l'administration.")
                return redirect("dashboard:index")

        # Retourne None pour indiquer à Django de continuer le traitement de la requête.
        return None
