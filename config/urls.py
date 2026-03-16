from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.shortcuts import redirect
from django.urls import include, path

from apps.accounts.views_setup import initial_setup, setup_complete

urlpatterns = [
    # One-time initial setup (returns 404 once an admin exists)
    path("setup/", initial_setup, name="setup"),
    path("setup/complete/", setup_complete, name="setup_complete"),
    path("admin/", admin.site.urls),
    # Endpoint de santé pour le monitoring (app health dédiée)
    path("api/", include("apps.health.urls")),
    # REST API
    path("api/v1/", include("apps.api.urls")),
    path("accounts/", include("apps.accounts.urls")),
    path("academics/", include("apps.academics.urls")),
    path("enrollments/", include("apps.enrollments.urls")),
    path("absences/", include("apps.absences.urls")),
    path("messaging/", include("apps.messaging.urls")),
    path("dashboard/", include("apps.dashboard.urls")),
    path("sessions/", include("apps.academic_sessions.urls")),
    path("audits/", include("apps.audits.urls")),
    path("", lambda request: redirect("dashboard:index", permanent=False)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
