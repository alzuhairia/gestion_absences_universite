"""
Vues pour l'endpoint de health check.
Permet de verifier que l'application Django et la base de donnees sont operationnelles.
"""

import logging
import ipaddress
import hmac

from django.conf import settings
from django.db import connection
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_ratelimit.decorators import ratelimit

from apps.audits.ip_utils import extract_client_ip, ratelimit_client_ip

logger = logging.getLogger(__name__)


def _health_rate_limit(group, request) -> str:
    return settings.HEALTHCHECK_RATE_LIMIT


def _health_allowlist_networks():
    networks = []
    for cidr in settings.HEALTHCHECK_ALLOWLIST_CIDRS:
        try:
            networks.append(ipaddress.ip_network(cidr, strict=False))
        except ValueError:
            logger.warning("Ignoring invalid HEALTHCHECK_ALLOWLIST_CIDRS entry: %s", cidr)
    return networks


def _is_health_client_allowed(client_ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    return any(parsed in network for network in _health_allowlist_networks())


@require_http_methods(["GET"])
@ratelimit(key=ratelimit_client_ip, rate=_health_rate_limit, method='GET', block=False)
def health_check(request):
    """
    API — Endpoint de santé pour le monitoring.

    Authentification:
        Header X-Healthcheck-Token (requis) : token configuré dans HEALTHCHECK_TOKEN
        IP source doit être dans HEALTHCHECK_ALLOWLIST_CIDRS

    Réponses:
        200 {"status": "ok"}
        403 {"status": "error", "error": "Forbidden"}  — IP non autorisée ou token invalide
        429 {"status": "error", "error": "Too Many Requests"}  — rate limit (HEALTHCHECK_RATE_LIMIT)
        503 {"status": "error", "error": "Service unavailable"}  — DB inaccessible
    """
    # Never log query strings for this endpoint. This avoids accidental token leakage
    # from malformed requests sent with query parameters.
    request.META['QUERY_STRING'] = ''

    if getattr(request, 'limited', False):
        response = JsonResponse({"status": "error", "error": "Too Many Requests"}, status=429)
        response["Retry-After"] = "60"
        return response

    client_ip = extract_client_ip(request)
    if not _is_health_client_allowed(client_ip):
        return JsonResponse({"status": "error", "error": "Forbidden"}, status=403)

    valid_tokens = [token for token in getattr(settings, 'HEALTHCHECK_VALID_TOKENS', []) if token]
    if not valid_tokens:
        logger.error("HEALTHCHECK_TOKEN is not configured; refusing health endpoint access.")
        return JsonResponse({"status": "error", "error": "Forbidden"}, status=403)

    provided = request.headers.get("X-Healthcheck-Token", "")
    if not provided:
        return JsonResponse({"status": "error", "error": "Forbidden"}, status=403)

    if not any(hmac.compare_digest(str(provided), str(expected)) for expected in valid_tokens):
        return JsonResponse({"status": "error", "error": "Forbidden"}, status=403)

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return JsonResponse({"status": "ok"}, status=200)
    except Exception:
        logger.exception("Health check failed")
        return JsonResponse(
            {
                "status": "error",
                "error": "Service unavailable",
            },
            status=503,
        )

