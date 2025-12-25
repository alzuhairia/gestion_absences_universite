from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.core.paginator import Paginator
from apps.accounts.models import User
from .models import LogAudit
from apps.dashboard.decorators import secretary_required

@login_required
@secretary_required
def audit_list(request):
    """
    Vue pour lister et rechercher les journaux d'audit.
    """
    query = request.GET.get('q', '')
    role_filter = request.GET.get('role', '')
    niveau_filter = request.GET.get('niveau', '')
    
    logs = LogAudit.objects.select_related('id_utilisateur').order_by('-date_action')
    
    if query:
        logs = logs.filter(
            Q(action__icontains=query) |
            Q(id_utilisateur__email__icontains=query) |
            Q(id_utilisateur__nom__icontains=query) |
            Q(id_utilisateur__prenom__icontains=query)
        )
    
    if role_filter:
        logs = logs.filter(id_utilisateur__role=role_filter)
    
    if niveau_filter:
        logs = logs.filter(niveau=niveau_filter)
    
    # Pagination
    paginator = Paginator(logs, 50)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'audits/log_list.html', {
        'page_obj': page_obj,
        'query': query,
        'role_filter': role_filter,
        'niveau_filter': niveau_filter,
    })
