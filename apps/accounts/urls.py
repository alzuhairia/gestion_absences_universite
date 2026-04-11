"""
FICHIER : apps/accounts/urls.py
RESPONSABILITE : Routes URL pour l'authentification et les profils
"""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views, views_2fa

app_name = "accounts"

urlpatterns = [
    path("login/", views.RateLimitedLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("profile/", views.profile_view, name="profile"),
    # 2FA TOTP
    path("2fa/setup/", views_2fa.setup_2fa, name="setup_2fa"),
    path("2fa/verify/", views_2fa.verify_2fa, name="verify_2fa"),
    path("2fa/disable/", views_2fa.disable_2fa, name="disable_2fa"),
    path("2fa/backup-codes/", views_2fa.backup_codes_view, name="backup_codes"),
    path(
        "2fa/backup-codes/regenerate/",
        views_2fa.regenerate_backup_codes,
        name="regenerate_backup_codes",
    ),
    # Password Change
    path(
        "password_change/",
        views.CustomPasswordChangeView.as_view(),
        name="password_change",
    ),
    path(
        "password_change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="accounts/password_change_done.html"
        ),
        name="password_change_done",
    ),
    # Password Reset
    path(
        "password_reset/",
        views.CustomPasswordResetView.as_view(),
        name="password_reset",
    ),
    path(
        "password_reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="accounts/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        views.CustomPasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="accounts/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("download-report/", views.download_report_pdf, name="download_report"),
]
