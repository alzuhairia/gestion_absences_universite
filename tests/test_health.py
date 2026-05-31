"""Tests de sécurité de l'endpoint healthcheck.

Vérifie que la vue ``health:health_check`` :
    - refuse les jetons passés en query-string (?token=...) — vecteur
      de fuite via les logs des reverse-proxies
    - n'accepte le jeton que via l'entête HTTP ``X-Healthcheck-Token``
    - tolère un jeton précédent (rotation) durant une fenêtre de grâce
    - rejette tout jeton invalide ou absent (403, JSON)

Tous les tests s'exécutent sous HTTPS simulé (``secure=True``) et
remplacent les réglages sensibles via ``override_settings`` pour ne
pas dépendre de l'environnement (.env).
"""
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(
    HEALTHCHECK_ALLOWLIST_CIDRS=["127.0.0.1/32"],
    HEALTHCHECK_RATE_LIMIT="1000/m",
    HEALTHCHECK_TOKEN="current-token",
    HEALTHCHECK_VALID_TOKENS=["current-token", "previous-token"],
)
class HealthcheckSecurityTests(TestCase):
    """Tests de sécurité de l'endpoint ``health_check`` (jeton en entête, rotation, no-store)."""

    def setUp(self):
        """Résout l'URL du healthcheck pour chaque test."""
        self.url = reverse("health:health_check")

    def test_query_token_is_refused(self):
        """Un jeton passé en query-string doit être refusé (vecteur de fuite via les logs)."""
        response = self.client.get(f"{self.url}?token=current-token", secure=True)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_header_token_is_accepted(self):
        """Le jeton courant fourni via l'entête ``X-Healthcheck-Token`` est accepté."""
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN="current-token",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})

    def test_invalid_token_returns_403(self):
        """Un jeton inconnu produit une 403 JSON sans détail compromettant."""
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN="wrong-token",
            secure=True,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")

    def test_previous_rotated_token_is_accepted(self):
        """Pendant la fenêtre de grâce, le jeton précédent reste accepté."""
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN="previous-token",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertJSONEqual(response.content, {"status": "ok"})

    def test_cache_control_no_store_on_200(self):
        """Une réponse 200 OK doit interdire toute mise en cache via ``Cache-Control: no-store``."""
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN="current-token",
            secure=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_cache_control_no_store_on_403(self):
        """Une réponse 403 doit également porter ``Cache-Control: no-store``."""
        response = self.client.get(
            self.url,
            HTTP_X_HEALTHCHECK_TOKEN="wrong-token",
            secure=True,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Cache-Control"], "no-store")
