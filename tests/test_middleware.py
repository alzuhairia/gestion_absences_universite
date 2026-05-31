"""
Tests — résilience du middleware d'inactivité de session quand Redis tombe.
"""
from unittest.mock import MagicMock

from django.test import RequestFactory, TestCase

from apps.accounts.middleware import SessionInactivityMiddleware
from apps.accounts.models import User


class SessionMiddlewareRedisDownTest(TestCase):
    """Vérifie que ``SessionInactivityMiddleware`` reste robuste face à une panne du backend session."""

    def setUp(self):
        """Crée un utilisateur étudiant et instancie le middleware avec un get_response sentinelle."""
        self.factory = RequestFactory()
        self.user = User.objects.create_user(
            email="user@example.com",
            password="testpass123",
            nom="Test",
            prenom="User",
            role=User.Role.ETUDIANT,
        )
        self.response_sentinel = object()
        self.middleware = SessionInactivityMiddleware(lambda req: self.response_sentinel)

    def test_session_middleware_redis_down_does_not_crash(self):
        """Si le backend de session lève une exception, le middleware ne doit ni planter ni déconnecter l'utilisateur."""
        request = self.factory.get("/")
        request.user = self.user

        # Simule une session cassée (ex. connexion Redis refusée)
        broken_session = MagicMock()
        broken_session.get.side_effect = ConnectionError("Redis is down")
        request.session = broken_session

        response = self.middleware(request)

        # Le middleware doit déléguer à get_response sans planter
        self.assertIs(response, self.response_sentinel)

    def test_session_middleware_normal_flow_unaffected(self):
        """Une requête authentifiée normale doit toujours mettre à jour ``_last_activity``."""
        request = self.factory.get("/")
        request.user = self.user
        request.session = {}

        response = self.middleware(request)

        self.assertIs(response, self.response_sentinel)
        self.assertIn("_last_activity", request.session)
