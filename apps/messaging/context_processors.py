"""
Context processor pour rendre le nombre de messages non lus disponible dans tous les templates.
"""

def unread_messages_count(request):
    """
    Ajoute le nombre de messages non lus au contexte pour les utilisateurs authentifiés.
    """
    if request.user.is_authenticated:
        from .models import Message
        unread_count = Message.objects.filter(
            destinataire=request.user,
            lu=False
        ).count()
        return {
            'unread_messages_count': unread_count,
            'has_unread_messages': unread_count > 0,
        }
    return {
        'unread_messages_count': 0,
        'has_unread_messages': False,
    }

