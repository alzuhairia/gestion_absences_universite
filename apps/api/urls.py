"""
FICHIER : apps/api/urls.py
RESPONSABILITE : Routes URL de l'API REST (router DRF + endpoints custom)
"""
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter

from . import views

app_name = "api"

router = DefaultRouter()
router.register(r"students", views.StudentViewSet, basename="student")
router.register(r"courses", views.CoursViewSet, basename="course")
router.register(r"enrollments", views.InscriptionViewSet, basename="enrollment")
router.register(r"absences", views.AbsenceViewSet, basename="absence")
router.register(
    r"justifications", views.JustificationViewSet, basename="justification"
)

urlpatterns = [
    # OpenAPI schema + interactive docs
    path("schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "docs/",
        SpectacularSwaggerView.as_view(url_name="api:schema"),
        name="swagger-ui",
    ),
    path(
        "redoc/",
        SpectacularRedocView.as_view(url_name="api:schema"),
        name="redoc",
    ),
    # Analytics & exports
    path(
        "analytics/dashboard/",
        views.dashboard_analytics,
        name="analytics-dashboard",
    ),
    path(
        "analytics/statistics/",
        views.statistics_analytics,
        name="analytics-statistics",
    ),
    path(
        "exports/student-pdf/<int:student_id>/",
        views.export_student_pdf_api,
        name="export-student-pdf",
    ),
    path(
        "exports/at-risk-excel/",
        views.export_at_risk_excel_api,
        name="export-at-risk-excel",
    ),
    path(
        "notifications/",
        views.NotificationViewSet.as_view({"get": "list"}),
        name="notification-list",
    ),
    path(
        "notifications/<int:pk>/read/",
        views.NotificationViewSet.as_view({"post": "mark_read"}),
        name="notification-read",
    ),
    path(
        "notifications/read-all/",
        views.NotificationViewSet.as_view({"post": "mark_all_read"}),
        name="notification-read-all",
    ),
    # Router (CRUD endpoints)
    path("", include(router.urls)),
]
