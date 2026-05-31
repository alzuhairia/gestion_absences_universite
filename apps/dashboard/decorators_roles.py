"""
Décorateurs de contrôle d'accès basé sur les rôles pour le tableau de bord UniAbsences.

Ce module constitue la fondation sécuritaire de l'application : chaque vue
protégée doit être encadrée par l'un de ces décorateurs afin que seuls les
utilisateurs disposant du rôle approprié puissent y accéder.

Conception sécuritaire :
  - Chaque décorateur effectue une vérification de rôle et redirige avec un
    message d'erreur en cas d'échec, plutôt que de lever un 403, afin
    d'offrir aux utilisateurs un chemin clair vers la suite.
  - Les vues sont censées appliquer un second contrôle de propriété en
    leur sein (par ex. vérifier ``course.professeur == request.user``)
    pour un contrôle fin.
  - Les rôles sont strictement séparés ; ADMIN est exclu des opérations
    quotidiennes (présences, inscriptions) et les secrétaires gèrent
    ces flux à la place.

Decorators
----------
``admin_required``      : rôle ADMIN uniquement.
``secretary_required``  : rôle SECRETAIRE uniquement.
``professor_required``  : rôle PROFESSEUR uniquement.
``student_required``    : rôle ETUDIANT uniquement.
``roles_required``      : accepte un tuple de rôles — autorise plusieurs rôles.

Fait partie du système de tableau de bord UniAbsences.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect

from apps.accounts.models import User


def admin_required(view_func):
    """
    Restreint une vue aux utilisateurs ayant le rôle ADMIN.

    Les administrateurs sont responsables de la configuration du système
    (facultés, départements, cours, utilisateurs, années académiques)
    et de la revue des journaux d'audit.  Ils sont explicitement exclus
    des tâches opérationnelles quotidiennes telles que l'inscription
    des étudiants et l'approbation des justifications — celles-ci sont
    prises en charge par le rôle de secrétaire.

    Notes d'implémentation :
    - Utilise ``@user_passes_test`` comme première barrière (redirige
      vers la connexion lorsque l'utilisateur n'est pas authentifié).
    - Une seconde vérification en ligne au sein de ``wrapper`` ajoute un
      message d'erreur clair afin que les non-administrateurs
      authentifiés soient redirigés vers l'index du tableau de bord
      avec un retour explicite plutôt qu'une simple 302.

    Parameters
    ----------
    view_func : callable
        La fonction de vue à protéger.

    Returns
    -------
    callable
        La fonction de vue encapsulée qui applique la vérification du rôle ADMIN.
    """

    def check_admin(user):
        """Retourne True si l'utilisateur est authentifié et possède le rôle ADMIN."""
        return user.is_authenticated and user.role == User.Role.ADMIN

    # user_passes_test de Django gère le cas non authentifié en
    # redirigeant vers la page de connexion avant l'exécution de notre wrapper.
    decorated_view = user_passes_test(
        check_admin, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """Vérifie le rôle ADMIN et redirige avec message d'erreur si l'utilisateur n'est pas admin."""
        if not check_admin(request.user):
            messages.error(request, "Accès réservé aux administrateurs.")
            return redirect("dashboard:index")
        return decorated_view(request, *args, **kwargs)

    return wrapper


def secretary_required(view_func):
    """
    Restreint une vue aux utilisateurs ayant le rôle SECRETAIRE.

    Les secrétaires prennent en charge toutes les tâches opérationnelles
    quotidiennes : inscription des étudiants, approbation/rejet des
    justifications, encodage direct des absences et gestion des
    dispenses de seuil.

    **Important** : le rôle ADMIN est explicitement exclu de ces vues.
    Cette séparation est cruciale pour la sécurité et l'auditabilité —
    les administrateurs ne doivent pas pouvoir modifier les données
    opérationnelles dont ils sont également responsables de l'audit.

    Lorsqu'un admin authentifié tente d'atteindre une vue réservée aux
    secrétaires, le décorateur ajoute un message d'avertissement
    explicatif (plutôt qu'une erreur générique) pour que l'admin
    comprenne l'intention de conception.

    Parameters
    ----------
    view_func : callable
        La fonction de vue à protéger.

    Returns
    -------
    callable
        La fonction de vue encapsulée qui applique la vérification du rôle SECRETAIRE.
    """

    def check_secretary(user):
        """Retourne True si l'utilisateur est authentifié et possède le rôle SECRETAIRE."""
        return user.is_authenticated and user.role == User.Role.SECRETAIRE

    decorated_view = user_passes_test(
        check_secretary, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """Vérifie le rôle SECRETAIRE et adapte le message d'erreur si l'appelant est admin."""
        if not check_secretary(request.user):
            # Affiche un message spécifique aux admins expliquant la séparation des rôles.
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
    Restreint une vue aux utilisateurs ayant le rôle PROFESSEUR.

    Les professeurs peuvent consulter leurs cours assignés, enregistrer
    les présences/absences pour chaque séance et consulter les
    résultats des justifications (lecture seule).

    **Important** : ce décorateur ne vérifie que le rôle.  Les
    vérifications de propriété individuelles (par ex.
    ``course.professeur == request.user``) doivent être effectuées dans
    la vue elle-même pour empêcher un professeur d'accéder aux données
    d'un autre professeur.

    Parameters
    ----------
    view_func : callable
        La fonction de vue à protéger.

    Returns
    -------
    callable
        La fonction de vue encapsulée qui applique la vérification du rôle PROFESSEUR.
    """

    def check_professor(user):
        """Retourne True si l'utilisateur est authentifié et possède le rôle PROFESSEUR."""
        return user.is_authenticated and user.role == User.Role.PROFESSEUR

    decorated_view = user_passes_test(
        check_professor, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """Vérifie le rôle PROFESSEUR et redirige avec un message d'erreur sinon."""
        if not check_professor(request.user):
            messages.error(request, "Accès réservé aux professeurs.")
            return redirect("dashboard:index")
        return decorated_view(request, *args, **kwargs)

    return wrapper


def roles_required(*allowed_roles):
    """
    Restreint une vue aux utilisateurs disposant de l'un des rôles spécifiés.

    Utilisez ce décorateur lorsqu'une même vue doit être accessible par
    plusieurs rôles distincts (par exemple, une page de téléchargement
    de justification qui doit être joignable à la fois par les
    secrétaires, les admins et l'étudiant concerné).  Les vérifications
    fines de propriété (par ex. « cet étudiant est le destinataire
    réel ») restent à la charge de la vue elle-même.

    Usage::

        @login_required
        @roles_required(User.Role.SECRETAIRE, User.Role.ADMIN)
        def my_view(request): ...

    Parameters
    ----------
    *allowed_roles : str
        Une ou plusieurs valeurs de ``User.Role`` autorisées à accéder
        à la vue décorée.

    Returns
    -------
    callable
        Un décorateur qui encapsule la fonction de vue avec la
        vérification de rôle.
    """
    # Conversion en set pour un test d'appartenance en O(1).
    allowed = set(allowed_roles)

    def decorator(view_func):
        """Décorateur paramétré qui encapsule ``view_func`` avec la vérification de rôles autorisés."""

        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            """Redirige les anonymes vers le login et rejette les rôles non autorisés."""
            user = request.user
            # Redirige les visiteurs non authentifiés vers la page de connexion.
            if not user.is_authenticated:
                return redirect("accounts:login")
            # Rejette les utilisateurs authentifiés dont le rôle n'est pas dans l'ensemble autorisé.
            if user.role not in allowed:
                messages.error(request, "Accès non autorisé.")
                return redirect("dashboard:index")
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator


def student_required(view_func):
    """
    Restreint une vue aux utilisateurs ayant le rôle ETUDIANT.

    Les étudiants peuvent consulter leurs propres inscriptions et leur
    historique d'absences, soumettre des documents de justification et
    suivre leur taux d'absence par cours.

    **Important** : ce décorateur ne vérifie que le rôle.  Les
    vérifications de propriété (par ex. ``inscription.id_etudiant ==
    request.user``) doivent être effectuées dans la vue pour empêcher
    un étudiant d'accéder aux données d'un autre étudiant.

    Parameters
    ----------
    view_func : callable
        La fonction de vue à protéger.

    Returns
    -------
    callable
        La fonction de vue encapsulée qui applique la vérification du rôle ETUDIANT.
    """

    def check_student(user):
        """Retourne True si l'utilisateur est authentifié et possède le rôle ETUDIANT."""
        return user.is_authenticated and user.role == User.Role.ETUDIANT

    decorated_view = user_passes_test(
        check_student, login_url="accounts:login"
    )(view_func)

    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        """Vérifie le rôle ETUDIANT et redirige avec un message d'erreur sinon."""
        if not check_student(request.user):
            messages.error(request, "Accès réservé aux étudiants.")
            return redirect("dashboard:index")
        return decorated_view(request, *args, **kwargs)

    return wrapper
