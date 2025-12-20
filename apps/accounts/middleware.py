# apps/accounts/middleware.py
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages

class RoleMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        return response
    
    def process_view(self, request, view_func, view_args, view_kwargs):
        # Vérifier les permissions par rôle si l'utilisateur est authentifié
        if request.user.is_authenticated:
            # Exemple: Vérifier l'accès à certaines vues
            path = request.path_info
            
            # Règles d'accès par rôle
            if path.startswith('/admin/') and not request.user.is_superuser:
                messages.error(request, "Accès non autorisé à l'administration.")
                return redirect('dashboard:home')
        
        return None