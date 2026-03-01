from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.cache import cache
from .models import Message
from .forms import MessageForm
from django.db.models import Q

def get_messaging_template(user, template_name):
    """
    Détermine le template de messagerie selon le rôle de l'utilisateur.
    """
    if user.role == user.Role.ADMIN:
        return f'messaging/admin_{template_name}.html'
    elif user.role == user.Role.SECRETAIRE:
        return f'messaging/secretary_{template_name}.html'
    elif user.role == user.Role.PROFESSEUR:
        return f'messaging/instructor_{template_name}.html'
    else:  # ETUDIANT
        return f'messaging/student_{template_name}.html'

@login_required
def inbox(request):
    """
    Boîte de réception - Affiche les messages reçus par l'utilisateur.
    """
    messages_list = Message.objects.filter(destinataire=request.user).order_by('-date_envoi')
    template = get_messaging_template(request.user, 'inbox')
    return render(request, template, {
        'message_list': messages_list, 
        'active_tab': 'inbox',
    })

@login_required
def sent_box(request):
    """
    Messages envoyés - Affiche les messages envoyés par l'utilisateur.
    """
    messages_list = Message.objects.filter(expediteur=request.user).order_by('-date_envoi')
    template = get_messaging_template(request.user, 'sent_box')
    return render(request, template, {
        'message_list': messages_list, 
        'active_tab': 'sent',
    })

@login_required
def compose(request):
    """
    Rédiger un nouveau message.
    """
    if request.method == 'POST':
        form = MessageForm(request.POST, user=request.user)
        if form.is_valid():
            message = form.save(commit=False)
            message.expediteur = request.user
            message.save()
            messages.success(request, "Message envoyé avec succès !")
            return redirect('messaging:sent')
    else:
        form = MessageForm(user=request.user)
    
    template = get_messaging_template(request.user, 'compose')
    return render(request, template, {
        'form': form,
    })

@login_required
def message_detail(request, message_id):
    """
    Détail d'un message - Affiche le contenu complet d'un message.
    """
    msg = get_object_or_404(Message, id_message=message_id)
    
    # Check permission (handle NULL expediteur/destinataire from SET_NULL)
    is_recipient = msg.destinataire_id is not None and msg.destinataire_id == request.user.pk
    is_sender = msg.expediteur_id is not None and msg.expediteur_id == request.user.pk
    if not is_recipient and not is_sender:
        messages.error(request, "Vous n'avez pas accès à ce message.")
        return redirect('messaging:inbox')

    # Mark as read if user is recipient
    if is_recipient and not msg.lu:
        msg.lu = True
        msg.save()
        cache.delete(f"messages:unread_count:{request.user.pk}")
    
    template = get_messaging_template(request.user, 'detail')
    return render(request, template, {
        'message': msg,
    })
