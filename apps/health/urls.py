"""
FICHIER : apps/health/urls.py
RESPONSABILITE : Route URL pour le health check endpoint
"""

from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    path("health/", views.health_check, name="health_check"),
]
