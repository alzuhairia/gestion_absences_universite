"""
Configuration des URL pour l'application de health check.

Expose un unique endpoint ``/health/`` sous le namespace ``health``.
Cet endpoint est destiné à être consommé par des outils externes de
supervision (par ex. Uptime Kuma, Prometheus blackbox exporter) et est
protégé par une authentification par token et des vérifications
d'allowlist IP.

Appartient à : UniAbsences — app health.
"""

from django.urls import path

from . import views

app_name = "health"

urlpatterns = [
    # GET /health/ — retourne {"status": "ok"} quand l'app et la BD sont saines.
    path("health/", views.health_check, name="health_check"),
]
