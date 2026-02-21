"""
Décorateurs de sécurité pour les différents modules (Admin, Secrétaire, Professeur, Étudiant).

IMPORTANT POUR LA SOUTENANCE :
Ces décorateurs sont la base du système de sécurité et de gestion des permissions.
Ils garantissent que seuls les utilisateurs autorisés peuvent accéder aux fonctionnalités
correspondant à leur rôle.

Principe de sécurité :
- Double vérification : décorateur + vérification dans la vue
- Messages explicites en cas d'accès non autorisé
- Redirection vers le dashboard approprié
- Séparation stricte des rôles (ADMIN exclu des opérations quotidiennes)
"""
import uuid
from functools import wraps
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from django.contrib import messages
from django.http import JsonResponse
from apps.accounts.models import User


def api_ok(payload=None, status=200):
    """
    Retourne une JsonResponse cohÃ©rente sans imposer un format unique.
    - dict: retour standard JsonResponse
    - list/primitive: safe=False pour conserver le contrat API existant
    """
    if payload is None:
        payload = {"ok": True}
    if isinstance(payload, dict):
        return JsonResponse(payload, status=status)
    return JsonResponse(payload, safe=False, status=status)


def new_request_id() -> str:
    """Correlation id court pour tracer les erreurs API dans les logs."""
    return uuid.uuid4().hex[:12]


def api_error(message, status=400, *, code=None, request_id=None):
    """Retourne une erreur JSON uniforme."""
    payload = {
        "error": {
            "code": code or "bad_request",
            "message": message,
        }
    }
    if request_id:
        payload["error"]["request_id"] = request_id
    return JsonResponse(payload, status=status)


def api_login_required(view_func=None, *, roles=None):
    """
    Variante API de login_required.
    Retourne 401 JSON au lieu d'une redirection HTML vers la page de login.
    """
    allowed_roles = set(roles or [])

    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return api_error(
                    "Authentication required",
                    status=401,
                    code="auth_required",
                )
            if allowed_roles and request.user.role not in allowed_roles:
                return api_error(
                    "Forbidden",
                    status=403,
                    code="forbidden",
                )
            return func(request, *args, **kwargs)
        return wrapper

    if view_func is not None:
        return decorator(view_func)
    return decorator


def admin_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un administrateur.
    
    Rôle ADMIN :
    - Configuration système (facultés, départements, cours, utilisateurs)
    - Consultation des journaux d'audit
    - Gestion des années académiques
    - NE PEUT PAS effectuer d'opérations quotidiennes (inscriptions, validation justificatifs)
    
    Utilise @user_passes_test pour une sécurité renforcée au niveau Django.
    
    Args:
        view_func: La fonction de vue à protéger
        
    Returns:
        Fonction wrapper qui vérifie le rôle avant d'exécuter la vue
    """
    def check_admin(user):
        """
        Vérifie si l'utilisateur est un administrateur.
        
        Args:
            user: L'utilisateur à vérifier
            
        Returns:
            True si l'utilisateur est authentifié et a le rôle ADMIN, False sinon
        """
        return user.is_authenticated and user.role == User.Role.ADMIN
    
    # Utilisation de user_passes_test de Django pour une sécurité renforcée
    decorated_view = user_passes_test(
        check_admin,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """
        Wrapper qui vérifie le rôle et affiche un message d'erreur si nécessaire.
        """
        if not check_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper


def secretary_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un secrétaire.
    
    IMPORTANT : ADMIN est explicitement EXCLU des tâches opérationnelles.
    Cette séparation est critique pour la sécurité et la traçabilité.
    
    Rôle SECRETAIRE :
    - Inscription des étudiants (par niveau ou par cours)
    - Validation/refus des justificatifs d'absence
    - Encodage direct d'absences justifiées
    - Modification des absences
    - Gestion des exemptions au seuil de 40%
    
    Args:
        view_func: La fonction de vue à protéger
        
    Returns:
        Fonction wrapper qui vérifie le rôle avant d'exécuter la vue
    """
    def check_secretary(user):
        """
        Vérifie si l'utilisateur est un secrétaire (ADMIN exclu).
        
        IMPORTANT : Un ADMIN ne peut pas accéder aux fonctions secrétariat.
        Cela garantit la séparation des responsabilités :
        - ADMIN = Configuration système
        - SECRETAIRE = Opérations quotidiennes
        
        Args:
            user: L'utilisateur à vérifier
            
        Returns:
            True si l'utilisateur est authentifié et a le rôle SECRETAIRE, False sinon
        """
        return user.is_authenticated and user.role == User.Role.SECRETAIRE
    
    decorated_view = user_passes_test(
        check_secretary,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """
        Wrapper qui vérifie le rôle et affiche un message approprié.
        
        Si un ADMIN tente d'accéder, un message d'avertissement explicite est affiché
        pour expliquer la séparation des responsabilités.
        """
        if not check_secretary(request.user):
            # Message spécial pour les ADMIN qui tentent d'accéder
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
    
    Rôle PROFESSEUR :
    - Consultation de ses cours assignés
    - Saisie des présences/absences pour chaque séance
    - Consultation des absences justifiées (lecture seule)
    - Historique des séances et appels
    
    IMPORTANT : Le professeur ne peut accéder qu'à ses propres cours.
    Cette vérification doit être faite dans la vue elle-même (vérification de propriété).
    
    Args:
        view_func: La fonction de vue à protéger
        
    Returns:
        Fonction wrapper qui vérifie le rôle avant d'exécuter la vue
    """
    def check_professor(user):
        """
        Vérifie si l'utilisateur est un professeur.
        
        Args:
            user: L'utilisateur à vérifier
            
        Returns:
            True si l'utilisateur est authentifié et a le rôle PROFESSEUR, False sinon
        """
        return user.is_authenticated and user.role == User.Role.PROFESSEUR
    
    decorated_view = user_passes_test(
        check_professor,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """
        Wrapper qui vérifie le rôle et affiche un message d'erreur si nécessaire.
        """
        if not check_professor(request.user):
            messages.error(request, "Accès réservé aux professeurs.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper


def student_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un étudiant.
    
    Rôle ETUDIANT :
    - Consultation de ses cours et inscriptions
    - Visualisation de ses absences (justifiées/non justifiées)
    - Soumission de justificatifs d'absence
    - Suivi du taux d'absence par cours
    
    IMPORTANT : L'étudiant ne peut accéder qu'à ses propres données.
    Cette vérification doit être faite dans la vue elle-même (vérification de propriété).
    
    Args:
        view_func: La fonction de vue à protéger
        
    Returns:
        Fonction wrapper qui vérifie le rôle avant d'exécuter la vue
    """
    def check_student(user):
        """
        Vérifie si l'utilisateur est un étudiant.
        
        Args:
            user: L'utilisateur à vérifier
            
        Returns:
            True si l'utilisateur est authentifié et a le rôle ETUDIANT, False sinon
        """
        return user.is_authenticated and user.role == User.Role.ETUDIANT
    
    decorated_view = user_passes_test(
        check_student,
        login_url='accounts:login',
        redirect_field_name=None
    )(view_func)
    
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """
        Wrapper qui vérifie le rôle et affiche un message d'erreur si nécessaire.
        """
        if not check_student(request.user):
            messages.error(request, "Accès réservé aux étudiants.")
            return redirect('dashboard:index')
        return decorated_view(request, *args, **kwargs)
    
    return wrapper

