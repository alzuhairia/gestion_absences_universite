"""
Utilitaires de réponse JSON et décorateurs d'authentification API pour le tableau de bord UniAbsences.

Fournit des helpers légers utilisés par les endpoints HTMX et AJAX du
tableau de bord pour retourner des enveloppes JSON cohérentes et gérer
l'authentification sans la redirection HTML par défaut de Django.

``api_ok``            : retourne ``{"ok": True, ...}`` ou une liste en réponse JSON.
``api_error``         : retourne ``{"error": {"code": ..., "message": ...}}`` en JSON.
``new_request_id``    : génère un court identifiant hexadécimal UUID pour la corrélation des requêtes.
``api_login_required``: décorateur qui retourne un JSON 401 pour les requêtes non
                        authentifiées au lieu de rediriger vers la page de connexion.

Fait partie du système de tableau de bord UniAbsences.
"""

import uuid
from functools import wraps

from django.http import JsonResponse


def api_ok(payload=None, status=200):
    """
    Construit une réponse JSON de succès avec une enveloppe cohérente.

    La stratégie de sérialisation dépend du type de payload :

    - ``None``  → ``{"ok": True}`` (acquittement de succès par défaut).
    - ``dict``  → ``JsonResponse`` standard (``safe=True`` est implicite).
    - tout autre type (liste, primitive) → ``JsonResponse`` avec
      ``safe=False`` afin de préserver le contrat d'API existant pour
      les endpoints renvoyant des listes.

    Parameters
    ----------
    payload : dict | list | None, optional
        Les données à sérialiser.  Par défaut ``{"ok": True}`` si
        omis.
    status : int, optional
        Code de statut HTTP pour la réponse.  Par défaut ``200``.

    Returns
    -------
    JsonResponse
        Une réponse HTTP JSON contenant le payload sérialisé.
    """
    if payload is None:
        payload = {"ok": True}
    if isinstance(payload, dict):
        return JsonResponse(payload, status=status)
    # Les listes et autres types non-dict nécessitent safe=False dans Django.
    return JsonResponse(payload, safe=False, status=status)


def new_request_id() -> str:
    """
    Génère un court identifiant de corrélation hexadécimal pour le traçage des erreurs API.

    Returns
    -------
    str
        Une chaîne hexadécimale en minuscules de 12 caractères dérivée
        d'un UUID4 aléatoire.  Suffisamment courte pour figurer dans les
        lignes de log sans les surcharger.
    """
    return uuid.uuid4().hex[:12]


def api_error(message, status=400, *, code=None, request_id=None):
    """
    Construit une réponse d'erreur JSON uniforme.

    Le corps de la réponse suit toujours la structure::

        {
            "error": {
                "code": "<code>",
                "message": "<message>",
                "request_id": "<id>"   # uniquement lorsque request_id est fourni
            }
        }

    Parameters
    ----------
    message : str
        Description de l'erreur lisible par un humain.
    status : int, optional
        Code de statut HTTP.  Par défaut ``400``.
    code : str or None, optional
        Code d'erreur lisible par machine (par ex. ``"auth_required"``,
        ``"forbidden"``, ``"server_error"``).  Par défaut
        ``"bad_request"`` si omis.
    request_id : str or None, optional
        Identifiant de corrélation généré par ``new_request_id()``
        permettant de croiser les erreurs côté client avec les lignes
        de log côté serveur.

    Returns
    -------
    JsonResponse
        Une réponse HTTP JSON contenant l'enveloppe d'erreur et le
        statut fourni.
    """
    payload = {
        "error": {
            "code": code or "bad_request",
            "message": message,
        }
    }
    if request_id:
        payload["error"]["request_id"] = request_id
    return JsonResponse(payload, status=status)


def api_login_required(view_func=None, *, roles=None):
    """
    Variante adaptée aux API du décorateur ``@login_required`` de Django.

    Contrairement au décorateur standard, celui-ci retourne une réponse
    d'erreur JSON au lieu de rediriger vers la page de connexion HTML —
    ce qui correspond aux attentes des appelants HTMX et AJAX.

    Peut être utilisé de deux manières::

        # Sans restriction de rôle :
        @api_login_required
        def my_view(request): ...

        # Avec restriction de rôle :
        @api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
        def my_view(request): ...

    Échecs d'authentification et d'autorisation :

    - Non authentifié → JSON 401 ``{"error": {"code": "auth_required"}}``.
    - Mauvais rôle    → JSON 403 ``{"error": {"code": "forbidden"}}``.

    Parameters
    ----------
    view_func : callable or None
        Lorsqu'utilisé sans arguments (``@api_login_required``), Django
        transmet directement la fonction décorée ici.  Lorsqu'utilisé
        avec des arguments (``@api_login_required(roles=[...])``), il
        vaut ``None`` et un décorateur paramétré est renvoyé.
    roles : list[str] or None, optional
        Valeurs autorisées de ``User.role``.  Lorsqu'il vaut ``None`` ou
        est vide, tout utilisateur authentifié est autorisé.

    Returns
    -------
    callable
        La fonction de vue décorée (si ``view_func`` a été fourni), ou
        une fabrique de décorateur prête à encapsuler une vue.
    """
    allowed_roles = set(roles or [])

    def decorator(func):
        """Décorateur paramétré qui encapsule ``func`` avec les vérifications auth + rôles JSON."""

        @wraps(func)
        def wrapper(request, *args, **kwargs):
            """Renvoie 401/403 en JSON selon l'état d'authentification et le rôle de l'appelant."""
            # Rejette les appelants non authentifiés avec un payload JSON 401.
            if not request.user.is_authenticated:
                return api_error(
                    "Authentication required",
                    status=401,
                    code="auth_required",
                )
            # Rejette les utilisateurs authentifiés dont le rôle n'est pas dans l'ensemble autorisé.
            if allowed_roles and request.user.role not in allowed_roles:
                return api_error(
                    "Forbidden",
                    status=403,
                    code="forbidden",
                )
            return func(request, *args, **kwargs)

        return wrapper

    # Prend en charge à la fois @api_login_required et @api_login_required(roles=[...]).
    if view_func is not None:
        return decorator(view_func)
    return decorator
