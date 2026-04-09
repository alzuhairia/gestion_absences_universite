"""
FICHIER : tests/test_2fa.py
RESPONSABILITE : Tests pour l'authentification a deux facteurs (TOTP)
COUVERTURE :
  - Setup 2FA : enrolment, validation premier code, persistance secret
  - Verify 2FA : middleware gate, codes valides/invalides, rate limit
  - Disable 2FA : confirmation par mot de passe
  - Login flow : redirection vers verify_2fa quand 2FA active
"""

import pyotp
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.views_2fa import (
    ATTEMPTS_SESSION_KEY,
    MAX_VERIFY_ATTEMPTS,
    SETUP_SECRET_SESSION_KEY,
    VERIFIED_SESSION_KEY,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorSetupTests(TestCase):
    """Tests pour l'enrolment 2FA (vue setup_2fa)."""

    def setUp(self):
        self.user = User.objects.create_user(
            email="totp-setup@example.com",
            nom="Setup",
            prenom="User",
            password="StrongPass123!",
            role=User.Role.ETUDIANT,
        )
        self.client.force_login(self.user)
        self.url = reverse("accounts:setup_2fa")

    def test_get_setup_generates_secret_and_qr(self):
        """GET /accounts/2fa/setup/ doit afficher un QR code et stocker un secret en session."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("qr_data_uri", response.context)
        self.assertTrue(response.context["qr_data_uri"].startswith("data:image/png;base64,"))
        self.assertIn(SETUP_SECRET_SESSION_KEY, self.client.session)
        # Le secret n'est PAS encore persiste en DB
        self.user.refresh_from_db()
        self.assertEqual(self.user.two_factor_secret, "")
        self.assertFalse(self.user.two_factor_enabled)

    def test_post_valid_token_activates_2fa(self):
        """POST avec un code TOTP valide doit activer la 2FA et persister le secret."""
        # GET d'abord pour generer le secret
        self.client.get(self.url)
        secret = self.client.session[SETUP_SECRET_SESSION_KEY]
        valid_token = pyotp.TOTP(secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, secret)
        # Session marquee comme verifiee + secret de setup nettoye
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))
        self.assertNotIn(SETUP_SECRET_SESSION_KEY, self.client.session)

    def test_post_invalid_token_does_not_activate_2fa(self):
        """POST avec un code invalide ne doit PAS activer la 2FA."""
        self.client.get(self.url)

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 302)  # redirige vers setup_2fa avec error

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_already_enabled_redirects_to_profile(self):
        """Si la 2FA est deja activee, le setup doit rediriger vers le profil."""
        self.user.two_factor_secret = pyotp.random_base32()
        self.user.two_factor_enabled = True
        self.user.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:profile"))


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorVerifyTests(TestCase):
    """Tests pour la verification post-login (vue verify_2fa + middleware)."""

    def setUp(self):
        self.secret = pyotp.random_base32()
        self.user = User.objects.create_user(
            email="totp-verify@example.com",
            nom="Verify",
            prenom="User",
            password="StrongPass123!",
            role=User.Role.ETUDIANT,
        )
        self.user.two_factor_secret = self.secret
        self.user.two_factor_enabled = True
        self.user.save()
        self.url = reverse("accounts:verify_2fa")

    def test_middleware_blocks_dashboard_until_verified(self):
        """Sans validation 2FA, l'acces au dashboard doit etre redirige vers verify_2fa."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("verify", response.url)

    def test_post_valid_token_marks_session_verified(self):
        """POST avec un code TOTP valide doit marquer la session 2fa_verified."""
        self.client.force_login(self.user)
        valid_token = pyotp.TOTP(self.secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_post_invalid_token_increments_attempts(self):
        """POST avec un code invalide doit incrementer le compteur de tentatives."""
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session.get(ATTEMPTS_SESSION_KEY), 1)
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_too_many_failed_attempts_logs_user_out(self):
        """Apres MAX_VERIFY_ATTEMPTS echecs, l'utilisateur doit etre deconnecte."""
        self.client.force_login(self.user)
        # Simuler MAX_VERIFY_ATTEMPTS tentatives prealables
        session = self.client.session
        session[ATTEMPTS_SESSION_KEY] = MAX_VERIFY_ATTEMPTS
        session.save()

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:login"))
        # User deconnecte
        response2 = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response2.status_code, 302)
        self.assertIn("login", response2.url)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorDisableTests(TestCase):
    """Tests pour la desactivation de la 2FA."""

    def setUp(self):
        self.password = "StrongPass123!"
        self.user = User.objects.create_user(
            email="totp-disable@example.com",
            nom="Disable",
            prenom="User",
            password=self.password,
            role=User.Role.ETUDIANT,
        )
        self.user.two_factor_secret = pyotp.random_base32()
        self.user.two_factor_enabled = True
        self.user.save()
        self.client.force_login(self.user)
        # Marquer la session comme deja 2FA-verified pour passer le middleware
        session = self.client.session
        session[VERIFIED_SESSION_KEY] = True
        session.save()
        self.url = reverse("accounts:disable_2fa")

    def test_disable_with_correct_password(self):
        """Soumettre le bon mot de passe doit desactiver la 2FA."""
        response = self.client.post(self.url, {"password": self.password})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_disable_with_wrong_password_fails(self):
        """Un mauvais mot de passe ne doit PAS desactiver la 2FA."""
        response = self.client.post(self.url, {"password": "WrongPass!"})
        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertNotEqual(self.user.two_factor_secret, "")


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorLoginFlowTests(TestCase):
    """Tests d'integration : flux de login complet avec 2FA."""

    def test_login_with_2fa_redirects_to_verify(self):
        """
        Apres un login valide, si l'utilisateur a la 2FA activee,
        il doit etre redirige vers verify_2fa et NON vers le dashboard.
        """
        secret = pyotp.random_base32()
        user = User.objects.create_user(
            email="totp-login@example.com",
            nom="Login",
            prenom="User",
            password="StrongPass123!",
            role=User.Role.ETUDIANT,
        )
        user.two_factor_secret = secret
        user.two_factor_enabled = True
        user.save()

        response = self.client.post(
            reverse("accounts:login"),
            {"username": user.email, "password": "StrongPass123!"},
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("verify", response.url)
        # La session ne doit PAS etre marquee verifiee tant que le code n'a pas ete saisi
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))
