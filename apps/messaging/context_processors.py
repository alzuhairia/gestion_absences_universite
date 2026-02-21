"""
Context processor pour rendre le nombre de messages non lus disponible dans tous les templates.
"""

from django.core.cache import cache


def unread_messages_count(request):
    """
    Ajoute le nombre de messages non lus au contexte pour les utilisateurs authentifies.
    """
    if request.user.is_authenticated:
        from .models import Message

        cache_key = f"messages:unread_count:{request.user.pk}"
        try:
            unread_count = cache.get(cache_key)
        except Exception:
            unread_count = None

        if unread_count is None:
            unread_count = Message.objects.filter(
                destinataire=request.user,
                lu=False,
            ).count()
            # Cache court pour limiter les requetes repetitives sur les pages dashboard.
            try:
                cache.set(cache_key, unread_count, timeout=60)
            except Exception:
                pass

        return {
            "unread_messages_count": unread_count,
            "has_unread_messages": unread_count > 0,
        }

    return {
        "unread_messages_count": 0,
        "has_unread_messages": False,
    }
