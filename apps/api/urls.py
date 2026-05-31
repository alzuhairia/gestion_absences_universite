"""
Configuration des URL pour l'API REST UniAbsences.

Ce module relie deux groupes de patterns d'URL :

1. **Endpoints CRUD basés sur un router** — un ``DefaultRouter`` DRF enregistre
   les cinq ViewSets de ressources principaux et génère automatiquement les
   patterns d'URL standards ``list``, ``create``, ``retrieve``, ``update``,
   ``partial_update`` et ``destroy`` pour chaque ressource.

2. **Endpoints déclarés manuellement** — endpoints d'analytiques, d'export, de
   notifications et de documentation OpenAPI qui ne correspondent pas au modèle
   standard de ressources du router.

Toutes les URL dans ce fichier sont montées sous le préfixe ``api/`` défini
dans le ``config/urls.py`` racine. L'espace de noms ``app_name = "api"`` permet
à d'autres parties du projet de résoudre ces URL en inverse avec le préfixe
``api:``, par exemple ``reverse("api:analytics-dashboard")``.

Responsabilités :
  - Enregistrer les ViewSets avec le router DRF pour produire les patterns d'URL CRUD.
  - Exposer les endpoints de schéma OpenAPI, Swagger UI et documentation ReDoc
    (fournis par drf-spectacular).
  - Déclarer les endpoints d'analytiques pour les KPI du tableau de bord et les
    statistiques d'absences.
  - Déclarer les endpoints d'export pour les rapports PDF étudiants et les
    fichiers Excel des étudiants à risque.
  - Déclarer les endpoints de notifications (liste, marquer comme lu, tout marquer comme lu).

Fait partie de l'API REST UniAbsences.
"""

from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from . import views

# Espace de noms utilisé pour le reversing d'URL dans tout le projet
app_name = "api"

# ---------------------------------------------------------------------------
# Router DRF — endpoints CRUD pour les ressources principales
# ---------------------------------------------------------------------------
router = DefaultRouter()
# Gestion des étudiants : GET/POST /students/, GET/PUT/PATCH/DELETE /students/{id}/
router.register(r"students", views.StudentViewSet, basename="student")
# Gestion des cours : GET/POST /courses/, GET/PUT/PATCH/DELETE /courses/{id}/
router.register(r"courses", views.CoursViewSet, basename="course")
# Gestion des inscriptions : GET/POST /enrollments/, ... /enrollments/{id}/
router.register(r"enrollments", views.InscriptionViewSet, basename="enrollment")
# Gestion des absences : GET/POST /absences/, ... /absences/{id}/
router.register(r"absences", views.AbsenceViewSet, basename="absence")
# Gestion des justifications : GET/POST /justifications/, ... /justifications/{id}/
router.register(
    r"justifications", views.JustificationViewSet, basename="justification"
)

urlpatterns = [
    # ------------------------------------------------------------------
    # Schéma OpenAPI + documentation interactive (drf-spectacular)
    # ------------------------------------------------------------------
    # Schéma OpenAPI 3 brut — consommé par Swagger UI et ReDoc ci-dessous
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    # Swagger UI — explorateur d'API interactif basé sur le navigateur
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="api:schema"),
        name="swagger-ui",
    ),
    # ReDoc — documentation alternative de référence API en lecture seule
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="api:schema"),
        name="redoc",
    ),

    # ------------------------------------------------------------------
    # Endpoints d'analytiques (admin uniquement ; retournent des statistiques JSON calculées)
    # ------------------------------------------------------------------
    # Compteurs KPI haut niveau pour le tableau de bord administrateur
    path(
        "analytics/dashboard/",
        views.dashboard_analytics,
        name="analytics-dashboard",
    ),
    # Statistiques détaillées d'absences utilisées par les graphiques (par département, niveau, mois...)
    path(
        "analytics/statistics/",
        views.statistics_analytics,
        name="analytics-statistics",
    ),

    # ------------------------------------------------------------------
    # Endpoints d'export (génèrent des fichiers téléchargeables)
    # ------------------------------------------------------------------
    # Rapport PDF d'absence individuel d'étudiant — accessible par l'étudiant
    # lui-même ou par admin/secrétaire
    path(
        "exports/student-pdf/<int:student_id>/",
        views.export_student_pdf_api,
        name="export-student-pdf",
    ),
    # Export Excel en masse de tous les étudiants dépassant actuellement le seuil
    # d'absences — restreint aux rôles admin et secrétaire
    path(
        "exports/at-risk-excel/",
        views.export_at_risk_excel_api,
        name="export-at-risk-excel",
    ),

    # ------------------------------------------------------------------
    # Endpoints de notifications (limités à l'utilisateur authentifié)
    # ------------------------------------------------------------------
    # Lister toutes les notifications de l'utilisateur courant
    path(
        "notifications/",
        views.NotificationViewSet.as_view({"get": "list"}),
        name="notification-list",
    ),
    # Marquer une seule notification comme lue par sa clé primaire
    path(
        "notifications/<int:pk>/read/",
        views.NotificationViewSet.as_view({"post": "mark_read"}),
        name="notification-read",
    ),
    # Marquer en masse toutes les notifications non lues comme lues pour l'utilisateur courant
    path(
        "notifications/read-all/",
        views.NotificationViewSet.as_view({"post": "mark_all_read"}),
        name="notification-read-all",
    ),

    # ------------------------------------------------------------------
    # Endpoints CRUD générés par le router (doivent venir en dernier pour que les chemins manuels
    # ci-dessus aient la priorité sur tout pattern catch-all généré par le router)
    # ------------------------------------------------------------------
    path("", include(router.urls)),
]
