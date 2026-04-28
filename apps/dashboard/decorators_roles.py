"""
FICHIER : apps/dashboard/decorators_roles.py
RESPONSABILITE : Décorateurs de contrôle d'accès par rôle (Admin, Secrétaire, Professeur, Étudiant)

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

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect

from apps.accounts.models import User


def admin_required(view_func):
    """
    Décorateur qui vérifie que l'utilisateur est un administrateur.

    Rôle ADMIN :
    - Configuration système (facultés, départements, cours, utilisateurs)
    - Consultation des journaux d'audit
    - Gestion des années académiques
    - NE PEUT PAS effectuer d'opérations quotidiennes (inscriptions, validation justificatifs)

    Utilise @user_passes_test pour une sécurité renforcée au niveau Django.
    """

    def check_admin(user):
        return user.is_authenticated and user.role == User.Role.ADMIN

    decorated_view = user_passes_test(
        check_admin, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect("dashboard:index")
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
    """

    def check_secretary(user):
        return user.is_authenticated and user.role == User.Role.SECRETAIRE

    decorated_view = user_passes_test(
        check_secretary, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_secretary(request.user):
            if request.user.is_authenticated and request.user.role == User.Role.ADMIN:
                messages.warning(
                    request,
                    "Cette fonction est réservée au secrétariat. "
                    "Les administrateurs gèrent la configuration, pas les opérations quotidiennes.",
                )
            else:
                messages.error(request, "Accès réservé aux secrétaires.")
            return redirect("dashboard:index")
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
    """

    def check_professor(user):
        return user.is_authenticated and user.role == User.Role.PROFESSEUR

    decorated_view = user_passes_test(
        check_professor, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_professor(request.user):
            messages.error(request, "Accès réservé aux professeurs.")
            return redirect("dashboard:index")
        return decorated_view(request, *args, **kwargs)

    return wrapper


def roles_required(*allowed_roles):
    """
    Décorateur qui n'autorise que les utilisateurs portant l'un des rôles fournis.

    À utiliser quand plusieurs rôles distincts doivent partager la même vue
    (ex. téléchargement d'un justificatif accessible au secrétariat, à l'admin
    et à l'étudiant propriétaire). Les vérifications de propriété fines
    (« cet étudiant est bien le destinataire ») restent à la charge de la vue.

    Usage::

        @login_required
        @roles_required(User.Role.SECRETAIRE, User.Role.ADMIN)
        def my_view(request): ...
    """
    allowed = set(allowed_roles)

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            user = request.user
            if not user.is_authenticated:
                return redirect("accounts:login")
            if user.role not in allowed:
                messages.error(request, "Accès non autorisé.")
                return redirect("dashboard:index")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


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
    """

    def check_student(user):
        return user.is_authenticated and user.role == User.Role.ETUDIANT

    decorated_view = user_passes_test(
        check_student, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not check_student(request.user):
            messages.error(request, "Accès réservé aux étudiants.")
            return redirect("dashboard:index")
        return decorated_view(request, *args, **kwargs)

    return wrapper
