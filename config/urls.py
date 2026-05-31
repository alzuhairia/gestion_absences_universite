"""
Configuration racine des URL pour le projet UniAbsences.

Responsabilités :
  - Monte l'endpoint d'installation initiale de l'administrateur (renvoie
    404 dès qu'un administrateur existe).
  - Monte le site d'administration intégré de Django.
  - Monte le namespace d'URL de chaque application sous un préfixe de
    chemin dédié.
  - Sert les fichiers media et static localement lorsque DEBUG vaut True.

Résumé de la carte des URL :
  /setup/           — création initiale du superutilisateur (accounts.views_setup)
  /admin/           — interface d'administration Django
  /api/             — endpoint de health check (apps.health)
  /api/v1/          — API REST (apps.api)
  /accounts/        — authentification, profil, 2FA (apps.accounts)
  /academics/       — facultés, départements, cours (apps.academics)
  /enrollments/     — gestion des inscriptions étudiantes (apps.enrollments)
  /absences/        — saisie d'absences et justification (apps.absences)
  /messaging/       — messagerie interne (apps.messaging)
  /dashboard/       — vues du tableau de bord selon le rôle (apps.dashboard)
  /sessions/        — sessions académiques / séances (apps.academic_sessions)
  /audits/          — visualiseur du journal d'audit (apps.audits)
  /                 — redirection racine → index du tableau de bord

Fait partie de la configuration du projet UniAbsences.
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from apps.accounts.views_setup import initial_setup, setup_complete

urlpatterns = [
    # Installation initiale ponctuelle (renvoie 404 dès qu'un administrateur existe)
    path("setup/", initial_setup, name="setup"),
    path("setup/complete/", setup_complete, name="setup_complete"),
    path("admin/", admin.site.urls),
    # Endpoint de health check pour le monitoring (application health dédiée)
    path("api/", include("apps.health.urls")),
    # API REST (basée sur DRF, versionnée sous /api/v1/)
    path("api/v1/", include("apps.api.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("academics/", include("apps.academics.urls")),
    path("enrollments/", include("apps.enrollments.urls")),
    path("absences/", include("apps.absences.urls")),
    path("messaging/", include("apps.messaging.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("sessions/", include("apps.academic_sessions.urls")),
    path("audits/", include("apps.audits.urls")),
    # Redirection racine — les utilisateurs non authentifiés sont redirigés par le décorateur de login
    path("", lambda request: redirect("dashboard:index", permanent=False)),
]

# Sert les fichiers media téléversés et les assets statiques via le serveur de développement de Django.
# En production, ils doivent être servis directement par le serveur web (Nginx, etc.).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
