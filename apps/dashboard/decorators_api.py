"""
FICHIER : apps/dashboard/decorators_api.py
RESPONSABILITE : Utilitaires de réponse JSON et authentification API
"""

import uuid
from functools import wraps

from django.http import JsonResponse


def api_ok(payload=None, status=200):
    """
    Retourne une JsonResponse cohérente sans imposer un format unique.
    - dict: retour standard JsonResponse
    - list/primitive: safe=False pour conserver le contrat API existant
    """
    if payload is None:
        payload = {"ok": True}
    if isinstance(payload, dict):
        return JsonResponse(payload, status=status)
    return JsonResponse(payload, safe=False, status=status)


def new_request_id() -> str:
    """Correlation id court pour tracer les erreurs API dans les logs."""
    return uuid.uuid4().hex[:12]


def api_error(message, status=400, *, code=None, request_id=None):
    """Retourne une erreur JSON uniforme."""
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
    Variante API de login_required.
    Retourne 401 JSON au lieu d'une redirection HTML vers la page de login.
    """
    allowed_roles = set(roles or [])

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return api_error(
                    "Authentication required",
                    status=401,
                    code="auth_required",
                )
            if allowed_roles and request.user.role not in allowed_roles:
                return api_error(
                    "Forbidden",
                    status=403,
                    code="forbidden",
                )
            return func(request, *args, **kwargs)

        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator
