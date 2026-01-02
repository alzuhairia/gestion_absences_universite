"""
URLs pour l'app health.
Définit l'endpoint /api/health/ pour le monitoring.
"""
from django.urls import path
from . import views

app_name = 'health'

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
]
