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
            user = request.user
            
            # Vérifier si l'utilisateur doit changer son mot de passe
            # Exclure les URLs de changement de mot de passe et de déconnexion
            path = request.path_info
            excluded_paths = [
                '/accounts/password_change/',
                '/accounts/password_change/done/',
                '/accounts/logout/',
                '/accounts/login/',
            ]
            
            # Vérifier si le chemin actuel est exclu
            is_excluded = any(path.startswith(excluded) for excluded in excluded_paths)
            
            if not is_excluded and hasattr(user, 'must_change_password') and user.must_change_password:
                messages.warning(
                    request,
                    "Vous devez changer votre mot de passe avant de continuer."
                )
                return redirect('accounts:password_change')
            
            # Exemple: Vérifier l'accès à certaines vues
            # Règles d'accès par rôle
            if path.startswith('/admin/') and not request.user.is_superuser:
                messages.error(request, "Accès non autorisé à l'administration.")
                return redirect('dashboard:index')
        
        return None