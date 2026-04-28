"""
Consultation des journaux d'audit (rôle secrétaire).

Fonctionnalités :
  - Liste des logs d'audit avec filtres (rôle, action, date, utilisateur)
  - Recherche textuelle dans les actions
"""

import logging
from datetime import date as date_type

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.utils import safe_get_page
from apps.audits.models import LogAudit
from apps.dashboard.decorators import secretary_required

logger = logging.getLogger(__name__)


@login_required
@secretary_required
@require_http_methods(["GET"])
def secretary_audit_logs(request):
    """Consultation de tous les journaux d'audit avec filtres (pour secrétaire)"""

    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    user_filter = request.GET.get("user", "")
    search_query = request.GET.get("q", "")

    logs = LogAudit.objects.select_related("id_utilisateur").all()

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        try:
            date_type.fromisoformat(date_from)
            logs = logs.filter(date_action__gte=date_from)
        except ValueError:
            pass
    if date_to:
        try:
            date_type.fromisoformat(date_to)
            logs = logs.filter(date_action__date__lte=date_to)
        except ValueError:
            pass
    if user_filter:
        logs = logs.filter(
            Q(id_utilisateur__nom__icontains=user_filter)
            | Q(id_utilisateur__prenom__icontains=user_filter)
            | Q(id_utilisateur__email__icontains=user_filter)
        )
    if search_query:
        logs = logs.filter(action__icontains=search_query)

    logs = logs.order_by("-date_action")

    paginator = Paginator(logs, 50)
    logs_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/secretary_audit_logs.html",
        {
            "logs": logs_page,
            "role_filter": role_filter,
            "action_filter": action_filter,
            "date_from": date_from,
            "date_to": date_to,
            "user_filter": user_filter,
            "search_query": search_query,
        },
    )
