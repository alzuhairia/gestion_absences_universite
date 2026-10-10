"""
Configuration des URL pour le système de comptes UniAbsences.

Tous les patterns d'URL de ce fichier sont montés sous le préfixe
``accounts/`` défini dans le ``config/urls.py`` racine. Le namespace
``app_name = "accounts"`` permet à d'autres modules de résoudre ces URL
avec le préfixe ``accounts:`` (par ex. ``reverse("accounts:login")``).

Regroupés par fonctionnalité :
  - Authentification : login, logout, contrôle de vérification 2FA.
  - Gestion du mot de passe : réinitialisation (demande + confirmation + done), changement.
  - Gestion 2FA : configuration, désactivation, codes de secours, régénération des codes de secours.
  - Profil : page de compte personnel, téléchargement du rapport PDF.

Repérage rapide du code source
------------------------------
Chaque route est précédée d'un commentaire ``# → <fichier>.py`` indiquant
le sous-module qui définit réellement la vue.  ``views.<nom>`` masque le
fichier source par la ré-exportation effectuée dans ``views.py`` ; ces
commentaires évitent toute recherche.  Les vues préfixées
``auth_views.*`` proviennent de ``django.contrib.auth``.

Fait partie du système de comptes UniAbsences.
"""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .mfa.mfa_views import (
    backup_codes_view,
    disable_2fa,
    regenerate_backup_codes,
    setup_2fa,
    verify_2fa,
)

app_name = "accounts"

urlpatterns = [
    # ------------------------------------------------------------------ #
    # Authentification                                                   #
    # ------------------------------------------------------------------ #

    # → views_auth.py (RateLimitedLoginView)
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),

    # → django.contrib.auth.views (LogoutView intégrée)
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # ------------------------------------------------------------------ #
    # Profil utilisateur                                                 #
    # ------------------------------------------------------------------ #

    # → views_profile.py (profile_view)
    path("profile/", views.profile_view, name="profile"),

    # → views_profile.py (download_report_pdf)
    path("download-report/", views.download_report_pdf, name="download_report"),

    # ------------------------------------------------------------------ #
    # Authentification à deux facteurs (TOTP)                            #
    # ------------------------------------------------------------------ #

    # → mfa/mfa_views.py
    path("2fa/setup/", setup_2fa, name="setup_2fa"),

    # → mfa/mfa_views.py
    path("2fa/verify/", verify_2fa, name="verify_2fa"),

    # → mfa/mfa_views.py
    path("2fa/disable/", disable_2fa, name="disable_2fa"),

    # → mfa/mfa_views.py
    path("2fa/backup-codes/", backup_codes_view, name="backup_codes"),

    # → mfa/mfa_views.py
    path(
        "2fa/backup-codes/regenerate/",
        regenerate_backup_codes,
        name="regenerate_backup_codes",
    ),

    # ------------------------------------------------------------------ #
    # Changement de mot de passe (utilisateur authentifié)               #
    # ------------------------------------------------------------------ #

    # → views_auth.py (CustomPasswordChangeView)
    path(
        "password_change/",
        views.CustomPasswordChangeView.as_view(),
        name="password_change",
    ),

    # → django.contrib.auth.views (PasswordChangeDoneView intégrée)
    path(
        "password_change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),

    # ------------------------------------------------------------------ #
    # Réinitialisation du mot de passe (mot de passe oublié)             #
    # ------------------------------------------------------------------ #

    # → views_auth.py (CustomPasswordResetView)
    path(
        "password_reset/",
        views.CustomPasswordResetView.as_view(),
        name="password_reset",
    ),

    # → django.contrib.auth.views (PasswordResetDoneView intégrée)
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),

    # → views_auth.py (CustomPasswordResetConfirmView)
    path(
        "reset/<uidb64>/<token>/",
        views.CustomPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),

    # → django.contrib.auth.views (PasswordResetCompleteView intégrée)
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
]
