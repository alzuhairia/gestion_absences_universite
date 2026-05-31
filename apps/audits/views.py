"""
Vues du journal d'audit pour le système UniAbsences.

Ce module fournit la vue liste du journal d'audit utilisée par les
tableaux de bord administrateur et secrétaire pour parcourir et
rechercher dans la table ``LogAudit``.

Vues
----
``audit_log_list``
    Liste paginée et filtrable des entrées du journal d'audit. Prend en
    charge la recherche plein texte sur les champs action, type d'objet
    et utilisateur, ainsi qu'un filtrage optionnel par niveau de gravité
    (INFO / WARNING / CRITIQUE).

Fait partie du système d'audit UniAbsences.
"""

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator

from apps.utils import safe_get_page
from django.db.models import Q
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.dashboard.decorators import secretary_required

from .models import LogAudit


@login_required
@secretary_required
@require_GET
def audit_list(request):
    """
    Affiche une liste paginée et recherchable des entrées du journal d'audit.

    L'accès est restreint aux utilisateurs authentifiés disposant du rôle
    secrétaire (ou supérieur) via le décorateur ``@secretary_required``.
    Seules les requêtes GET sont acceptées (``@require_GET``).

    Paramètres de requête
    ---------------------
    q : str, optionnel
        Terme de recherche libre. Comparé sans tenir compte de la casse
        au texte ``action``, ainsi qu'aux champs ``email``, ``nom`` et
        ``prenom`` de l'utilisateur agissant via une requête OR.
    role : str, optionnel
        Filtre les entrées sur les actions effectuées par les utilisateurs
        ayant le rôle indiqué (par ex. ``"PROFESSEUR"``, ``"SECRETAIRE"``).
    niveau : str, optionnel
        Filtre les entrées par niveau de gravité : ``"INFO"``,
        ``"WARNING"`` ou ``"CRITIQUE"``.
    page : str, optionnel
        Numéro de page pour la pagination (50 enregistrements par page).
        Les valeurs invalides ou hors plage sont gérées de manière
        sécurisée par ``safe_get_page``.

    Contexte de template
    --------------------
    page_obj : Page
        La page courante d'entrées ``LogAudit`` (avec ``id_utilisateur``
        pré-chargé via ``select_related`` pour éviter les requêtes N+1).
    query : str
        Le terme de recherche actif (renvoyé pour le champ de recherche).
    role_filter : str
        Le filtre de rôle actif (renvoyé pour le widget de filtre).
    niveau_filter : str
        Le filtre de gravité actif (renvoyé pour le widget de filtre).

    Retourne
    --------
    django.http.HttpResponse
        Template ``audits/log_list.html`` rendu.
    """
    query = request.GET.get("q", "")
    role_filter = request.GET.get("role", "")
    niveau_filter = request.GET.get("niveau", "")

    # On commence par tous les logs, du plus récent au plus ancien ; pré-chargement de l'utilisateur pour éviter les requêtes N+1
    logs = LogAudit.objects.select_related("id_utilisateur").order_by("-date_action")

    if query:
        # Combinaison OR de la recherche sur le texte d'action et les champs d'identité utilisateur
        logs = logs.filter(
            Q(action__icontains=query)
            | Q(id_utilisateur__email__icontains=query)
            | Q(id_utilisateur__nom__icontains=query)
            | Q(id_utilisateur__prenom__icontains=query)
        )

    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)

    if niveau_filter:
        logs = logs.filter(niveau=niveau_filter)

    # Pagination à 50 enregistrements par page ; safe_get_page gère les numéros de page invalides
    paginator = Paginator(logs, 50)
    page_obj = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "audits/log_list.html",
        {
            "page_obj": page_obj,
            "query": query,
            "role_filter": role_filter,
            "niveau_filter": niveau_filter,
        },
    )
