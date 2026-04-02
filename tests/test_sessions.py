from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User, UserSession


@override_settings(
    RATELIMIT_ENABLE=False,
    SECURE_SSL_REDIRECT=False,
)
class MaxSessionsPerUserTests(TestCase):
    """BUG #17 — Enforce a maximum of MAX_SESSIONS_PER_USER concurrent sessions."""

    def setUp(self):
        self.password = "Str0ng!Pass99"
        self.user = User.objects.create_user(
            email="session@test.com",
            nom="Test",
            prenom="User",
            password=self.password,
            role=User.Role.ETUDIANT,
        )
        self.login_url = reverse("accounts:login")

    def _login_new_client(self):
        """Create a fresh client, log in, and return (client, session_key)."""
        client = Client()
        response = client.post(
            self.login_url,
            {"username": self.user.email, "password": self.password},
        )
        # Successful login redirects (302)
        self.assertEqual(response.status_code, 302)
        session_key = client.session.session_key
        self.assertIsNotNone(session_key)
        return client, session_key

    def test_new_session_is_registered(self):
        """Each login creates a UserSession row."""
        self._login_new_client()
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 1)

    def test_max_sessions_per_user(self):
        """The 4th login evicts the oldest session, keeping at most 3."""
        sessions = []
        for _ in range(4):
            client, key = self._login_new_client()
            sessions.append((client, key))

        # Only 3 UserSession rows remain
        active = UserSession.objects.filter(user=self.user).order_by("-created_at")
        self.assertEqual(active.count(), UserSession.MAX_SESSIONS_PER_USER)

        # The oldest session (sessions[0]) was evicted from Django sessions table
        oldest_key = sessions[0][1]
        self.assertFalse(Session.objects.filter(session_key=oldest_key).exists())

        # The 3 most recent sessions are still valid
        for _, key in sessions[1:]:
            self.assertTrue(Session.objects.filter(session_key=key).exists())

    def test_five_logins_keeps_only_three(self):
        """Stress-test: 5 logins → exactly 3 sessions remain."""
        keys = []
        for _ in range(5):
            _, key = self._login_new_client()
            keys.append(key)

        self.assertEqual(
            UserSession.objects.filter(user=self.user).count(),
            UserSession.MAX_SESSIONS_PER_USER,
        )
        # The 2 oldest are gone
        for key in keys[:2]:
            self.assertFalse(Session.objects.filter(session_key=key).exists())
