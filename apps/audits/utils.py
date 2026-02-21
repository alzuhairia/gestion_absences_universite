from .models import LogAudit
from apps.accounts.models import User
from .ip_utils import extract_client_ip


def get_client_ip(request):
    """
    Extrait l'adresse IP du client depuis la requête Django.
    Gère les proxies et load balancers.
    """
    return extract_client_ip(request)


def log_action(user, action, request=None, niveau='INFO', objet_type=None, objet_id=None):
    """
    Crée une entrée dans le journal d'audit.
    
    Args:
        user: L'utilisateur effectuant l'action
        action: Description détaillée de l'action
        request: Objet requête Django optionnel pour extraire l'IP
        niveau: Niveau de criticité ('INFO', 'WARNING', 'CRITIQUE')
        objet_type: Type d'objet affecté ('USER', 'COURS', 'FACULTE', etc.)
        objet_id: ID de l'objet affecté
    """
    if not user or not user.is_authenticated:
        return

    ip = '0.0.0.0'
    if request:
        ip = get_client_ip(request)
    
    # Déterminer automatiquement le niveau si 'CRITIQUE' est dans l'action
    if 'CRITIQUE' in action.upper() and niveau == 'INFO':
        niveau = 'CRITIQUE'
    
    LogAudit.objects.create(
        id_utilisateur=user,
        action=action,
        adresse_ip=ip,
        niveau=niveau,
        objet_type=objet_type,
        objet_id=objet_id
    )
