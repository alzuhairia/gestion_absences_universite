"""
FICHIER : apps/api/permissions.py
RESPONSABILITE : Permissions DRF basees sur les roles utilisateur
FONCTIONNALITES PRINCIPALES :
  - IsAdmin : acces reserve aux administrateurs
  - IsSecretary : acces reserve aux secretaires
  - IsProfessor : acces reserve aux professeurs
  - IsStudent : acces reserve aux etudiants
  - IsAdminOrSecretary : acces admin ou secretaire
  - IsAdminOrSecretaryOrProfessor : acces admin, secretaire ou professeur
  - IsStaffOrReadOnly : ecriture admin/secretaire, lecture seule pour les autres
DEPENDANCES CLES : rest_framework.permissions, apps.accounts.models
"""

from typing import cast

from rest_framework.permissions import BasePermission

from apps.accounts.models import User


def _role(request):
    """Rôle de l'utilisateur authentifié, None pour un visiteur anonyme."""
    if not request.user.is_authenticated:
        return None
    return cast(User, request.user).role


class IsAdmin(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == User.Role.ADMIN


class IsSecretary(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == User.Role.SECRETAIRE


class IsProfessor(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == User.Role.PROFESSEUR


class IsStudent(BasePermission):
    def has_permission(self, request, view):
        return _role(request) == User.Role.ETUDIANT


class IsAdminOrSecretary(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in (
            User.Role.ADMIN,
            User.Role.SECRETAIRE,
        )


class IsAdminOrSecretaryOrProfessor(BasePermission):
    def has_permission(self, request, view):
        return _role(request) in (
            User.Role.ADMIN,
            User.Role.SECRETAIRE,
            User.Role.PROFESSEUR,
        )


class IsStaffOrReadOnly(BasePermission):
    """Admin/Secretary: full access. Professor/Student: read-only."""

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return _role(request) in (User.Role.ADMIN, User.Role.SECRETAIRE)
