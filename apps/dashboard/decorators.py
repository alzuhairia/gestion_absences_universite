"""
Décorateurs de sécurité pour les différents modules (Admin, Secrétaire, Professeur, Étudiant).
"""
from functools import wraps
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from django.contrib import messages
from apps.accounts.models import User


def admin_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un administrateur.
    Utilise @user_passes_test pour une sécurité renforcée.
    """
    def check_admin(user):
        """Vérifie si l'utilisateur est un administrateur"""
        return user.is_authenticated and user.role == User.Role.ADMIN
    
    decorated_view = user_passes_test(
        check_admin,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper


def secretary_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un secrétaire.
    ADMIN est explicitement EXCLU des tâches opérationnelles.
    """
    def check_secretary(user):
        """Vérifie si l'utilisateur est un secrétaire (ADMIN exclu)"""
        return user.is_authenticated and user.role == User.Role.SECRETAIRE
    
    decorated_view = user_passes_test(
        check_secretary,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_secretary(request.user):
            if request.user.is_authenticated and request.user.role == User.Role.ADMIN:
                messages.warning(
                    request, 
                    "Cette fonction est réservée au secrétariat. "
                    "Les administrateurs gèrent la configuration, pas les opérations quotidiennes."
                )
            else:
                messages.error(request, "Accès réservé aux secrétaires.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper


def professor_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un professeur.
    STRICT: Le professeur ne peut accéder qu'à ses propres cours.
    """
    def check_professor(user):
        """Vérifie si l'utilisateur est un professeur"""
        return user.is_authenticated and user.role == User.Role.PROFESSEUR
    
    decorated_view = user_passes_test(
        check_professor,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_professor(request.user):
            messages.error(request, "Accès réservé aux professeurs.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper


def student_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un étudiant.
    STRICT: L'étudiant ne peut accéder qu'à ses propres données.
    """
    def check_student(user):
        """Vérifie si l'utilisateur est un étudiant"""
        return user.is_authenticated and user.role == User.Role.ETUDIANT
    
    decorated_view = user_passes_test(
        check_student,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_student(request.user):
            messages.error(request, "Accès réservé aux étudiants.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper

