"""
FICHIER : apps/dashboard/views_admin_users_list.py
RESPONSABILITE : Liste, création, modification et audit des utilisateurs (admin)
"""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.utils import safe_get_page
from apps.accounts.models import User
from apps.audits.models import LogAudit
from apps.audits.utils import log_action
from apps.dashboard.decorators import admin_required
from apps.dashboard.forms_admin import UserForm

logger = logging.getLogger(__name__)


@login_required
@admin_required
@require_GET
def admin_users(request):
    """Liste et gestion des utilisateurs"""

    role_filter = request.GET.get("role", "")
    search_query = request.GET.get("q", "")
    active_filter = request.GET.get("active", "")

    users = User.objects.all()

    if role_filter:
        users = users.filter(role=role_filter)
    if search_query:
        users = users.filter(
            Q(nom__icontains=search_query)
            | Q(prenom__icontains=search_query)
            | Q(email__icontains=search_query)
        )
    if active_filter == "true":
        users = users.filter(actif=True)
    elif active_filter == "false":
        users = users.filter(actif=False)

    users = users.order_by("nom", "prenom")

    paginator = Paginator(users, 25)
    users_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_users.html",
        {
            "users": users_page,
            "role_filter": role_filter,
            "search_query": search_query,
            "active_filter": active_filter,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_create(request):
    """Création d'un nouvel utilisateur"""

    if request.method == "POST":
        form = UserForm(request.POST)
        if form.is_valid():
            user = form.save()
            log_action(
                request.user,
                f"CRITIQUE: Création de l'utilisateur '{user.email}' (Rôle: {user.get_role_display()}, Nom: {user.get_full_name()}) - Gestion des utilisateurs",
                request,
                niveau="CRITIQUE",
                objet_type="USER",
                objet_id=user.id_utilisateur,
            )
            messages.success(request, f"Utilisateur '{user.email}' créé avec succès.")
            return redirect("dashboard:admin_users")
    else:
        form = UserForm()

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "title": "Créer un utilisateur",
            "editing_user": None,
        },
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def admin_user_edit(request, user_id):
    """Modification d'un utilisateur"""

    user = get_object_or_404(User, id_utilisateur=user_id)

    if request.method == "POST":
        old_role = user.role
        old_active = user.actif
        form = UserForm(request.POST, instance=user)
        if form.is_valid():
            user = form.save()

            if old_role != user.role:
                try:
                    old_role_display = User.Role(old_role).label
                except ValueError:
                    old_role_display = old_role
                log_action(
                    request.user,
                    f"CRITIQUE: Modification du rôle de '{user.email}' de {old_role_display} à {user.get_role_display()} - Gestion des utilisateurs",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )
            if old_active != user.actif:
                action = "activé" if user.actif else "désactivé"
                log_action(
                    request.user,
                    f"CRITIQUE: Compte '{user.email}' {action} (Gestion des utilisateurs - {'Réactivation' if user.actif else 'Désactivation'})",
                    request,
                    niveau="CRITIQUE",
                    objet_type="USER",
                    objet_id=user.id_utilisateur,
                )

            messages.success(
                request, f"Utilisateur '{user.email}' modifié avec succès."
            )
            return redirect("dashboard:admin_users")
    else:
        form = UserForm(instance=user)

    return render(
        request,
        "dashboard/admin_user_form.html",
        {
            "form": form,
            "editing_user": user,
            "title": f"Modifier l'utilisateur {user.get_full_name()}",
        },
    )


@login_required
@admin_required
@require_GET
def admin_user_audit(request, user_id):
    """Consultation des journaux d'audit pour un utilisateur spécifique"""

    user = get_object_or_404(User, id_utilisateur=user_id)
    logs = LogAudit.objects.filter(id_utilisateur=user).order_by("-date_action")

    paginator = Paginator(logs, 50)
    logs_page = safe_get_page(paginator, request.GET.get("page"))

    return render(
        request,
        "dashboard/admin_user_audit.html",
        {
            "user": user,
            "logs": logs_page,
        },
    )
