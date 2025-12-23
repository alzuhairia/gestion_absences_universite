from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import Message
from .forms import MessageForm
from django.db.models import Q

@login_required
def inbox(request):
    messages_list = Message.objects.filter(destinataire=request.user).order_by('-date_envoi')
    return render(request, 'messaging/inbox.html', {'messages': messages_list, 'active_tab': 'inbox'})

@login_required
def sent_box(request):
    messages_list = Message.objects.filter(expediteur=request.user).order_by('-date_envoi')
    return render(request, 'messaging/sent_box.html', {'messages': messages_list, 'active_tab': 'sent'})

@login_required
def compose(request):
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
    
    return render(request, 'messaging/compose.html', {'form': form})

@login_required
def message_detail(request, message_id):
    msg = get_object_or_404(Message, id_message=message_id)
    
    # Check permission
    if msg.destinataire != request.user and msg.expediteur != request.user:
        messages.error(request, "Vous n'avez pas accès à ce message.")
        return redirect('messaging:inbox')
    
    # Mark as read if user is recipient
    if msg.destinataire == request.user and not msg.lu:
        msg.lu = True
        msg.save()
        
    return render(request, 'messaging/detail.html', {'message': msg})
