"""
API prérequis par niveau (rôle administrateur / secrétaire).

Règle métier : un cours de niveau N ne peut avoir que des prérequis de niveau < N.
  - Niveau 1 : aucun prérequis possible
  - Niveau 2 : prérequis d'Année 1 uniquement
  - Niveau 3 : prérequis d'Année 1 ou 2

Utilisé par le formulaire de création/modification de cours (appel AJAX).
"""

import logging

from django.views.decorators.http import require_GET
from django_ratelimit.decorators import ratelimit

from apps.academics.models import Cours
from apps.accounts.models import User
from apps.audits.ip_utils import ratelimit_client_ip
from apps.dashboard.decorators import (
    api_error,
    api_login_required,
    api_ok,
    new_request_id,
)

logger = logging.getLogger(__name__)


@ratelimit(key=ratelimit_client_ip, rate="30/5m", method="GET", block=False)
@api_login_required(roles=[User.Role.ADMIN, User.Role.SECRETAIRE])
@require_GET
def get_prerequisites_by_level(request):
    """
    API — Liste les cours disponibles comme prérequis selon le niveau cible.

    Query params:
        niveau    (int, requis)    : niveau cible (1, 2 ou 3)
        course_id (int, optionnel) : exclut ce cours des résultats (mode édition)

    Réponses:
        200 [{"id": int, "code": str, "name": str, "niveau": int, "display": str}, ...]
        400 {"error": {"code": "bad_request", "message": "..."}}
        429 Rate limit dépassé (30/5m par IP)
        500 {"error": {"code": "server_error", ...}}
    """
    if getattr(request, "limited", False):
        return api_error(
            "Trop de requetes. Reessayez plus tard.", status=429, code="rate_limited"
        )

    niveau = request.GET.get("niveau")
    course_id = request.GET.get("course_id", None)

    if not niveau:
        return api_error("niveau requis", status=400, code="bad_request")

    try:
        niveau = int(niveau)
    except ValueError:
        return api_error("niveau invalide", status=400, code="bad_request")

    try:
        if niveau == 1:
            prerequisites = Cours.objects.none()
        elif niveau == 2:
            prerequisites = Cours.objects.filter(actif=True, niveau=1)
        elif niveau == 3:
            prerequisites = Cours.objects.filter(actif=True, niveau__in=[1, 2])
        else:
            return api_error(
                "niveau invalide (doit être 1, 2 ou 3)", status=400, code="bad_request"
            )

        if course_id:
            try:
                prerequisites = prerequisites.exclude(id_cours=int(course_id))
            except ValueError:
                pass

        data = [
            {
                "id": course.id_cours,
                "code": course.code_cours,
                "name": course.nom_cours,
                "niveau": course.niveau,
                "display": f"[{course.code_cours}] {course.nom_cours} (Année {course.niveau})",
            }
            for course in prerequisites.order_by("niveau", "code_cours")
        ]

        return api_ok(data)
    except Exception:
        request_id = new_request_id()
        logger.exception(
            "Erreur API get_prerequisites_by_level [request_id=%s]", request_id
        )
        return api_error(
            "Une erreur interne est survenue.",
            status=500,
            code="server_error",
            request_id=request_id,
        )
