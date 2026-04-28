"""
FICHIER : apps/messaging/views.py
RESPONSABILITE : Messagerie interne entre utilisateurs
FONCTIONNALITES PRINCIPALES :
  - Boite de reception et messages envoyes
  - Composition de message avec filtrage destinataires par role
  - Detail message avec marquage lu automatique
DEPENDANCES CLES : messaging.models, messaging.forms
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q

from apps.utils import safe_get_page
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from apps.accounts.models import User

from .forms import MessageForm
from .models import Message

_ROLE_MESSAGING_CONTEXT = {
    User.Role.ADMIN: ("base_admin.html", "dashboard:admin_dashboard"),
    User.Role.SECRETAIRE: ("base_secretary.html", "dashboard:secretary_dashboard"),
    User.Role.PROFESSEUR: ("base_instructor.html", "dashboard:instructor_dashboard"),
    User.Role.ETUDIANT: ("base_student.html", "dashboard:student_dashboard"),
}


def _messaging_base_ctx(user):
    base_template, dashboard_url = _ROLE_MESSAGING_CONTEXT.get(
        user.role, ("base_student.html", "dashboard:student_dashboard")
    )
    return {"base_template": base_template, "dashboard_url": dashboard_url}


@login_required
@require_GET
def inbox(request):
    """
    Boîte de réception - Affiche les messages reçus par l'utilisateur.
    """
    messages_list = Message.objects.filter(
        destinataire=request.user
    ).select_related("expediteur").order_by("-date_envoi")
    paginator = Paginator(messages_list, 20)
    page_obj = safe_get_page(paginator, request.GET.get("page"))
    return render(
        request,
        "messaging/inbox.html",
        {
            **_messaging_base_ctx(request.user),
            "message_list": page_obj,
            "page_obj": page_obj,
            "active_tab": "inbox",
        },
    )


@login_required
@require_GET
def sent_box(request):
    """
    Messages envoyés - Affiche les messages envoyés par l'utilisateur.
    """
    messages_list = Message.objects.filter(
        expediteur=request.user
    ).select_related("destinataire").order_by("-date_envoi")
    paginator = Paginator(messages_list, 20)
    page_obj = safe_get_page(paginator, request.GET.get("page"))
    return render(
        request,
        "messaging/sent_box.html",
        {
            **_messaging_base_ctx(request.user),
            "message_list": page_obj,
            "page_obj": page_obj,
            "active_tab": "sent",
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def compose(request):
    """
    Rédiger un nouveau message.
    """
    if not request.user.actif:
        messages.error(request, "Votre compte est désactivé. Vous ne pouvez pas envoyer de messages.")
        return redirect("messaging:inbox")

    if request.method == "POST":
        form = MessageForm(request.POST, user=request.user)
        if form.is_valid():
            message = form.save(commit=False)
            message.expediteur = request.user
            if message.destinataire_id == request.user.pk:
                messages.error(
                    request, "Vous ne pouvez pas vous envoyer un message à vous-même."
                )
                return render(request, "messaging/compose.html", {
                    **_messaging_base_ctx(request.user),
                    "form": form,
                })
            # Server-side role check: students can only message professors/secretaries
            if request.user.role == User.Role.ETUDIANT:
                dest = message.destinataire
                if dest.role not in (User.Role.PROFESSEUR, User.Role.SECRETAIRE):
                    messages.error(
                        request,
                        "Vous ne pouvez envoyer des messages qu'aux professeurs et secrétaires.",
                    )
                    return render(request, "messaging/compose.html", {
                        **_messaging_base_ctx(request.user),
                        "form": form,
                    })
            message.save()
            messages.success(request, "Message envoyé avec succès !")
            return redirect("messaging:sent")
    else:
        form = MessageForm(user=request.user)

    return render(
        request,
        "messaging/compose.html",
        {
            **_messaging_base_ctx(request.user),
            "form": form,
        },
    )


@login_required
@require_GET
def message_detail(request, message_id):
    """
    Détail d'un message - Affiche le contenu complet d'un message.
    """
    msg = get_object_or_404(
        Message.objects.select_related("expediteur", "destinataire"),
        id_message=message_id,
    )

    # Check permission (handle NULL expediteur/destinataire from SET_NULL)
    is_recipient = (
        msg.destinataire_id is not None and msg.destinataire_id == request.user.pk
    )
    is_sender = msg.expediteur_id is not None and msg.expediteur_id == request.user.pk
    if not is_recipient and not is_sender:
        messages.error(request, "Vous n'avez pas accès à ce message.")
        return redirect("messaging:inbox")

    # Mark as read if user is recipient
    if is_recipient and not msg.lu:
        msg.mark_as_read()

    return render(
        request,
        "messaging/detail.html",
        {
            **_messaging_base_ctx(request.user),
            "message": msg,
        },
    )
