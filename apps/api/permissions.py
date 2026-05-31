"""
Classes de permission basées sur les rôles pour l'API REST UniAbsences.

L'authentification dans UniAbsences est basée sur les sessions (pas de tokens JWT).
Chaque classe de permission ci-dessous suppose que le middleware de session Django
a déjà rempli ``request.user``. Toutes les classes héritent de ``BasePermission``
de DRF et n'implémentent que ``has_permission`` ; les permissions au niveau objet
sont gérées au niveau du queryset à l'intérieur de chaque ViewSet.

Responsabilités :
  - IsAdmin                        : n'admet que les administrateurs (rôle ADMIN).
  - IsSecretary                    : n'admet que les secrétaires (rôle SECRETAIRE).
  - IsProfessor                    : n'admet que les enseignants (rôle PROFESSEUR).
  - IsStudent                      : n'admet que les étudiants (rôle ETUDIANT).
  - IsAdminOrSecretary             : admet administrateurs et secrétaires —
                                     utilisé pour les opérations d'écriture qui ne
                                     doivent pas être disponibles aux enseignants.
  - IsAdminOrSecretaryOrProfessor  : admet les trois rôles du personnel — utilisé pour
                                     l'enregistrement d'absences où les professeurs
                                     ont besoin d'un accès en écriture.
  - IsStaffOrReadOnly              : autorise les méthodes HTTP sûres à tout utilisateur
                                     authentifié ; restreint les méthodes de
                                     modification aux administrateurs/secrétaires uniquement.

Fait partie de l'API REST UniAbsences.
"""

from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from apps.accounts.models import User


class IsAdmin(BasePermission):
    """
    Accorde l'accès exclusivement aux utilisateurs avec le rôle ADMIN.

    Retourne True uniquement lorsque la requête est authentifiée et que le rôle
    de l'utilisateur est ``User.Role.ADMIN``. Utilisé pour les endpoints réservés
    aux administrateurs tels que les tableaux de bord d'analytiques et l'accès au
    journal d'audit.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle ADMIN, False sinon.
        """
        # Exige une session authentifiée et le rôle ADMIN
        return (
            request.user.is_authenticated and request.user.role == User.Role.ADMIN
        )


class IsSecretary(BasePermission):
    """
    Accorde l'accès exclusivement aux utilisateurs avec le rôle SECRETAIRE.

    Retourne True uniquement lorsque la requête est authentifiée et que le rôle
    de l'utilisateur est ``User.Role.SECRETAIRE``.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle SECRETAIRE, False sinon.
        """
        # Exige une session authentifiée et le rôle SECRETAIRE
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.SECRETAIRE
        )


class IsProfessor(BasePermission):
    """
    Accorde l'accès exclusivement aux utilisateurs avec le rôle PROFESSEUR.

    Retourne True uniquement lorsque la requête est authentifiée et que le rôle
    de l'utilisateur est ``User.Role.PROFESSEUR``.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle PROFESSEUR, False sinon.
        """
        # Exige une session authentifiée et le rôle PROFESSEUR
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.PROFESSEUR
        )


class IsStudent(BasePermission):
    """
    Accorde l'accès exclusivement aux utilisateurs avec le rôle ETUDIANT.

    Retourne True uniquement lorsque la requête est authentifiée et que le rôle
    de l'utilisateur est ``User.Role.ETUDIANT``. Utilisé sur l'endpoint de création
    de justification afin que seuls les étudiants puissent soumettre des
    justifications d'absence.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle ETUDIANT, False sinon.
        """
        # Exige une session authentifiée et le rôle ETUDIANT
        return (
            request.user.is_authenticated
            and request.user.role == User.Role.ETUDIANT
        )


class IsAdminOrSecretary(BasePermission):
    """
    Accorde l'accès aux utilisateurs avec le rôle ADMIN ou SECRETAIRE.

    Il s'agit du contrôle de niveau staff le plus courant utilisé pour les
    opérations d'écriture (création, mise à jour, suppression) sur les ressources
    que les professeurs et les étudiants ne doivent pas modifier, telles que les
    inscriptions, les dossiers étudiants et les endpoints d'export.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle ADMIN ou SECRETAIRE, False sinon.
        """
        # Autorise l'accès lorsque l'utilisateur détient l'un des deux rôles administratifs
        return request.user.is_authenticated and request.user.role in (
            User.Role.ADMIN,
            User.Role.SECRETAIRE,
        )


class IsAdminOrSecretaryOrProfessor(BasePermission):
    """
    Accorde l'accès aux utilisateurs avec le rôle ADMIN, SECRETAIRE ou PROFESSEUR.

    Utilisé pour les opérations d'écriture sur les absences (création/mise à jour)
    où les professeurs ont besoin de la possibilité d'enregistrer les absences
    pour leurs propres cours pendant que les administrateurs et les secrétaires
    conservent un accès complet.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si l'utilisateur a le rôle ADMIN, SECRETAIRE ou PROFESSEUR, False sinon.
        """
        # Admet les trois rôles du personnel ; les étudiants sont exclus
        return request.user.is_authenticated and request.user.role in (
            User.Role.ADMIN,
            User.Role.SECRETAIRE,
            User.Role.PROFESSEUR,
        )


class IsStaffOrReadOnly(BasePermission):
    """
    Accorde un accès en lecture seule à tous les utilisateurs authentifiés ; restreint
    l'accès en écriture aux administrateurs et secrétaires.

    Les méthodes HTTP sûres (GET, HEAD, OPTIONS) sont autorisées pour tout utilisateur
    authentifié quel que soit le rôle. Les méthodes de modification (POST, PUT, PATCH,
    DELETE) requièrent le rôle ADMIN ou SECRETAIRE.
    """

    def has_permission(self, request: Request, view: APIView) -> bool:  # type: ignore[override]
        """
        Vérifie si la requête doit être autorisée.

        Paramètres :
            request (Request) : la requête HTTP entrante.
            view (APIView) : la vue à laquelle on accède.

        Retourne :
            bool : True si lecture seule ou si l'utilisateur a un rôle administratif, False sinon.
        """
        # Les requêtes non authentifiées sont toujours refusées
        if not request.user.is_authenticated:
            return False
        # Les méthodes sûres (lecture seule) sont ouvertes à tous les utilisateurs authentifiés
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        # Les méthodes d'écriture sont restreintes aux rôles administratifs
        return request.user.role in (User.Role.ADMIN, User.Role.SECRETAIRE)
