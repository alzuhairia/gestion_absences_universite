"""
Vue du journal d'audit pour le tableau de bord secrétaire UniAbsences.

Ce module fournit au secrétaire une vue paginée et filtrable de toutes les entrées
du journal d'audit du système enregistrées par ``apps.audits.utils.log_action``.

``secretary_audit_logs``
    Affiche un tableau d'enregistrements ``LogAudit``, ordonné du plus récent au plus ancien.
    Prend en charge les paramètres de filtre indépendants suivants (tous combinables) :

    ``role``        — filtre par rôle de l'utilisateur agissant (correspondance exacte).
    ``action``      — filtre par texte d'action (sous-chaîne insensible à la casse).
    ``date_from``   — inclut uniquement les entrées à partir de cette date ISO.
    ``date_to``     — inclut uniquement les entrées jusqu'à cette date ISO.
    ``user``        — filtre par nom ou email de l'utilisateur agissant (sous-chaîne
                      insensible à la casse à travers nom, prenom, email).
    ``q``           — recherche en texte libre à travers le champ action.

    Les chaînes de date qui ne s'analysent pas comme des dates ISO valides sont silencieusement
    ignorées afin qu'un ``?date_from=`` invalide ne produise pas d'erreur 500.

    L'accès est réservé aux utilisateurs administrateurs/secrétaires authentifiés via
    ``@secretary_required``.

Fait partie du tableau de bord UniAbsences.
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
    """
    Affiche le tableau du journal d'audit paginé et filtrable.

    Tous les paramètres de filtre sont lus depuis la chaîne de requête GET. Chaque filtre est
    appliqué indépendamment et ils sont combinés avec une sémantique ET (c'est-à-dire que chaque
    filtre supplémentaire affine l'ensemble de résultats).

    Les chaînes de date ISO invalides pour ``date_from`` / ``date_to`` sont capturées et
    silencieusement ignorées — le filtre correspondant n'est tout simplement pas appliqué.

    Paramètres
    ----------
    request : HttpRequest
        GET d'un utilisateur secrétaire/administrateur authentifié.

    Retourne
    -------
    HttpResponse
        Affiche ``dashboard/secretary_audit_logs.html`` avec :

        ``logs`` : Page
            Page paginée d'objets ``LogAudit`` (50 par page).
        ``role_filter`` : str
            Valeur de filtre rôle actuelle (chaîne vide si non définie).
        ``action_filter`` : str
            Valeur de filtre action actuelle.
        ``date_from`` : str
            Valeur de filtre date-de actuelle (chaîne de date ISO ou vide).
        ``date_to`` : str
            Valeur de filtre date-à actuelle (chaîne de date ISO ou vide).
        ``user_filter`` : str
            Valeur de filtre nom/email d'utilisateur actuelle.
        ``search_query`` : str
            Valeur de recherche en texte libre actuelle.
    """
    # Lire tous les paramètres de filtre depuis la chaîne de requête.
    role_filter = request.GET.get("role", "")
    action_filter = request.GET.get("action", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    user_filter = request.GET.get("user", "")
    search_query = request.GET.get("q", "")

    logs = LogAudit.objects.select_related("id_utilisateur").all()

    # Appliquer les filtres incrémentalement — chaque appel retourne un nouveau queryset.
    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    if action_filter:
        logs = logs.filter(action__icontains=action_filter)
    if date_from:
        try:
            # Valider la chaîne de date avant de la transmettre à l'ORM.
            date_type.fromisoformat(date_from)
            logs = logs.filter(date_action__gte=date_from)
        except ValueError:
            # Ignorer silencieusement les chaînes de date non analysables.
            pass
    if date_to:
        try:
            date_type.fromisoformat(date_to)
            logs = logs.filter(date_action__date__lte=date_to)
        except ValueError:
            pass
    if user_filter:
        # Rechercher à travers nom, prénom et email avec une sémantique OU.
        logs = logs.filter(
            Q(id_utilisateur__nom__icontains=user_filter)
            | Q(id_utilisateur__prenom__icontains=user_filter)
            | Q(id_utilisateur__email__icontains=user_filter)
        )
    if search_query:
        logs = logs.filter(action__icontains=search_query)

    # Ordonner du plus récent au plus ancien pour la vue par défaut.
    logs = logs.order_by("-date_action")

    paginator = Paginator(logs, 50)
    # ``safe_get_page`` borne les numéros de page hors plage au lieu de lever une 404.
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
