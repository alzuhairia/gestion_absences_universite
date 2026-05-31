"""
Tests for Two-Factor Authentication (TOTP) in the UniAbsences project.

Coverage:
  - TwoFactorSetupTests     : enrolment flow (GET generates QR + secret,
                              valid/invalid POST, already-enabled redirect).
  - TwoFactorVerifyTests    : middleware gate, valid/invalid codes,
                              rate-limit lockout after MAX_VERIFY_ATTEMPTS.
  - TwoFactorDisableTests   : password-confirmation disablement.
  - TwoFactorLoginFlowTests : full login → redirect-to-verify integration.

All test classes suppress SSL redirect via @override_settings so that
the test client does not need to use ``secure=True`` on every request.

Part of the UniAbsences test suite.
"""

import pyotp
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.accounts.mfa.mfa_service import (
    ATTEMPTS_SESSION_KEY,
    MAX_VERIFY_ATTEMPTS,
    SETUP_SECRET_SESSION_KEY,
    VERIFIED_SESSION_KEY,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorSetupTests(TestCase):
    """
    Tests for the 2FA enrolment view (setup_2fa).

    Verifies that the setup page generates a TOTP secret and QR code on GET,
    activates 2FA on a valid POST, rejects an invalid code, and redirects
    away when 2FA is already enabled.
    """

    def setUp(self):
        """Create a student user and log them in before each test."""
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
        """GET /accounts/2fa/setup/ must render a QR code and store a secret in the session."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("qr_data_uri", response.context)
        self.assertTrue(response.context["qr_data_uri"].startswith("data:image/png;base64,"))
        self.assertIn(SETUP_SECRET_SESSION_KEY, self.client.session)
        # Secret must NOT be persisted to DB until the user validates the code.
        self.user.refresh_from_db()
        self.assertEqual(self.user.two_factor_secret, "")
        self.assertFalse(self.user.two_factor_enabled)

    def test_post_valid_token_activates_2fa(self):
        """POST with a valid TOTP code must activate 2FA and persist the secret to the DB."""
        # GET first to generate the session secret.
        self.client.get(self.url)
        secret = self.client.session[SETUP_SECRET_SESSION_KEY]
        valid_token = pyotp.TOTP(secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, secret)
        # Session must be marked as 2FA-verified and the setup secret must be cleared.
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))
        self.assertNotIn(SETUP_SECRET_SESSION_KEY, self.client.session)

    def test_post_invalid_token_does_not_activate_2fa(self):
        """POST with an invalid TOTP code must NOT enable 2FA."""
        self.client.get(self.url)

        response = self.client.post(self.url, {"token": "000000"})
        # Redirects back to setup with an error message.
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_already_enabled_redirects_to_profile(self):
        """If 2FA is already active, the setup view must redirect to the profile page."""
        self.user.two_factor_secret = pyotp.random_base32()
        self.user.two_factor_enabled = True
        self.user.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:profile"))


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorVerifyTests(TestCase):
    """
    Tests for the post-login 2FA verification view (verify_2fa) and middleware.

    Verifies that the middleware blocks protected views, that a valid code
    marks the session as verified, that invalid codes increment the attempt
    counter, and that exceeding MAX_VERIFY_ATTEMPTS logs the user out.
    """

    def setUp(self):
        """Create a user with 2FA already enabled and store the secret for TOTP generation."""
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
        """Without 2FA verification, accessing the dashboard must redirect to verify_2fa."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("verify", response.url)

    def test_post_valid_token_marks_session_verified(self):
        """A valid TOTP code must set the 2fa_verified flag in the session."""
        self.client.force_login(self.user)
        valid_token = pyotp.TOTP(self.secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_post_invalid_token_increments_attempts(self):
        """An invalid TOTP code must increment the attempt counter and return HTTP 400."""
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session.get(ATTEMPTS_SESSION_KEY), 1)
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_too_many_failed_attempts_logs_user_out(self):
        """
        After MAX_VERIFY_ATTEMPTS failures, the user must be logged out and
        redirected to the login page.
        """
        self.client.force_login(self.user)
        # Pre-seed the session with the maximum number of prior failures.
        session = self.client.session
        session[ATTEMPTS_SESSION_KEY] = MAX_VERIFY_ATTEMPTS
        session.save()

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:login"))
        # Confirm the user is actually logged out by checking a protected page.
        response2 = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response2.status_code, 302)
        self.assertIn("login", response2.url)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorDisableTests(TestCase):
    """
    Tests for the 2FA disablement view (disable_2fa).

    Verifies that submitting the correct password disables 2FA and that
    a wrong password is rejected without altering the 2FA state.
    """

    def setUp(self):
        """
        Create a user with 2FA enabled, log them in, and mark the session
        as already 2FA-verified so the middleware does not block the test.
        """
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
        # Bypass the 2FA middleware by marking the session as already verified.
        session = self.client.session
        session[VERIFIED_SESSION_KEY] = True
        session.save()
        self.url = reverse("accounts:disable_2fa")

    def test_disable_with_correct_password(self):
        """Correct password submission must disable 2FA and clear the secret."""
        response = self.client.post(self.url, {"password": self.password})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_disable_with_wrong_password_fails(self):
        """An incorrect password must be rejected and 2FA must remain enabled."""
        response = self.client.post(self.url, {"password": "WrongPass!"})
        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertNotEqual(self.user.two_factor_secret, "")


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorLoginFlowTests(TestCase):
    """
    Integration tests for the complete login flow when 2FA is enabled.

    Verifies that after a successful credential check the user is redirected
    to the 2FA verification page rather than directly to the dashboard, and
    that the session is not prematurely marked as verified.
    """

    def test_login_with_2fa_redirects_to_verify(self):
        """
        After a successful login, a user with 2FA enabled must be redirected
        to verify_2fa — NOT to the dashboard — and the session must NOT be
        marked as verified until the TOTP code is submitted.
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
        # Session must NOT be marked as 2FA-verified before the code is submitted.
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))
