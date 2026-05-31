"""
Tests — éviction automatique des sessions Django quand un utilisateur dépasse ``MAX_SESSIONS_PER_USER``.
"""
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User, UserSession


@override_settings(
    RATELIMIT_ENABLE=False,
    SECURE_SSL_REDIRECT=False,
)
class MaxSessionsPerUserTests(TestCase):
    """BUG #17 — impose un nombre maximum de sessions concurrentes par utilisateur."""

    def setUp(self):
        """Crée un utilisateur étudiant et résout l'URL de login pour les sessions de test."""
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
        """Crée un nouveau ``Client``, le connecte et retourne ``(client, session_key)``."""
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
        """Chaque login crée une ligne ``UserSession`` correspondante."""
        self._login_new_client()
        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 1)

    def test_max_sessions_per_user(self):
        """Le 4e login évince la session la plus ancienne, conservant au maximum 3 sessions actives."""
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
        """Test de charge : 5 logins consécutifs → il reste exactement 3 sessions actives."""
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
