"""
Configuration des URL pour l'application audits d'UniAbsences.

Monte la vue de liste du journal d'audit sous le préfixe ``audits/``
défini dans le ``config/urls.py`` racine. Le namespace ``app_name = "audits"``
permet la résolution inverse avec le préfixe ``audits:``.

Fait partie du système d'audit UniAbsences.
"""
from django.urls import path

from . import views

app_name = "audits"

urlpatterns = [
    path("logs/", views.audit_list, name="audit_list"),
]
