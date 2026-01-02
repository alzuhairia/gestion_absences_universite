"""
Vues pour l'endpoint de health check.
Permet de vérifier que l'application Django et la base de données sont opérationnelles.
"""
from django.http import JsonResponse
from django.db import connection
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
@require_http_methods(["GET"])
def health_check(request):
    """
    Endpoint de santé pour le monitoring.
    
    Vérifie que :
    - L'application Django fonctionne
    - La base de données PostgreSQL est accessible
    
    Retourne un JSON simple avec le statut.
    Utilisé par Uptime Kuma et autres outils de monitoring.
    
    Returns:
        JsonResponse: {"status": "ok"} avec HTTP 200 si tout est OK
        JsonResponse: {"status": "error", "error": "message"} avec HTTP 503 en cas d'erreur
    """
    try:
        # Vérifier la connexion à la base de données
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        
        # Tout est OK
        return JsonResponse({"status": "ok"}, status=200)
    
    except Exception as e:
        # Erreur de connexion à la base de données
        return JsonResponse({
            "status": "error",
            "error": str(e)
        }, status=503)
