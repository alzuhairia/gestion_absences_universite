from unittest.mock import MagicMock

from django.test import RequestFactory, TestCase

from apps.accounts.middleware import SessionInactivityMiddleware
from apps.accounts.models import User


class SessionMiddlewareRedisDownTest(TestCase):
    def setUp(self):
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
        """If the session backend raises, the middleware must not crash or log out the user."""
        request = self.factory.get("/")
        request.user = self.user

        # Simulate a broken session (e.g. Redis connection refused)
        broken_session = MagicMock()
        broken_session.get.side_effect = ConnectionError("Redis is down")
        request.session = broken_session

        response = self.middleware(request)

        # The middleware must fall through to get_response, not crash
        self.assertIs(response, self.response_sentinel)

    def test_session_middleware_normal_flow_unaffected(self):
        """Normal authenticated request still updates _last_activity."""
        request = self.factory.get("/")
        request.user = self.user
        request.session = {}

        response = self.middleware(request)

        self.assertIs(response, self.response_sentinel)
        self.assertIn("_last_activity", request.session)
