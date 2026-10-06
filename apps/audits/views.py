"""
FICHIER : apps/audits/views.py
RESPONSABILITE : Ancienne URL de consultation des logs d'audit
FONCTIONNALITES PRINCIPALES :
  - Redirige /audits/logs/ vers la page secretariat (dashboard:secretary_audit_logs)
DEPENDANCES CLES : dashboard.views_secretary.secretary_audit_logs
"""

from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.http import require_GET


@require_GET
def audit_list(request):
    """
    Ancienne page des journaux d'audit, remplacée par la page du secrétariat
    (filtres, pagination). On garde l'URL pour les favoris existants.
    """
    url = reverse("dashboard:secretary_audit_logs")
    query = request.GET.urlencode()
    return redirect(f"{url}?{query}" if query else url)
