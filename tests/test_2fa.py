"""
Tests pour l'authentification à deux facteurs (TOTP) dans le projet UniAbsences.

Couverture :
  - TwoFactorSetupTests     : flux d'activation (GET génère le QR + secret,
                              POST valide/invalide, redirection si déjà activé).
  - TwoFactorVerifyTests    : portail middleware, codes valides/invalides,
                              verrouillage après MAX_VERIFY_ATTEMPTS.
  - TwoFactorDisableTests   : désactivation après confirmation du mot de passe.
  - TwoFactorLoginFlowTests : intégration login complet → redirection vers verify.

Toutes les classes de tests désactivent la redirection SSL via @override_settings
afin que le client de test n'ait pas besoin d'utiliser ``secure=True`` à chaque requête.

Fait partie de la suite de tests UniAbsences.
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
    Tests pour la vue d'activation 2FA (setup_2fa).

    Vérifie que la page de configuration génère un secret TOTP et un QR code
    sur GET, active la 2FA sur un POST valide, rejette un code invalide, et
    redirige ailleurs lorsque la 2FA est déjà activée.
    """

    def setUp(self):
        """Crée un utilisateur étudiant et le connecte avant chaque test."""
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
        """GET /accounts/2fa/setup/ doit rendre un QR code et stocker un secret dans la session."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn("qr_data_uri", response.context)
        self.assertTrue(response.context["qr_data_uri"].startswith("data:image/png;base64,"))
        self.assertIn(SETUP_SECRET_SESSION_KEY, self.client.session)
        # Le secret ne doit PAS être persisté en BDD tant que l'utilisateur n'a pas validé le code.
        self.user.refresh_from_db()
        self.assertEqual(self.user.two_factor_secret, "")
        self.assertFalse(self.user.two_factor_enabled)

    def test_post_valid_token_activates_2fa(self):
        """POST avec un code TOTP valide doit activer la 2FA et persister le secret en BDD."""
        # GET d'abord pour générer le secret de session.
        self.client.get(self.url)
        secret = self.client.session[SETUP_SECRET_SESSION_KEY]
        valid_token = pyotp.TOTP(secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, secret)
        # La session doit être marquée comme 2FA-vérifiée et le secret de setup doit être effacé.
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))
        self.assertNotIn(SETUP_SECRET_SESSION_KEY, self.client.session)

    def test_post_invalid_token_does_not_activate_2fa(self):
        """POST avec un code TOTP invalide ne doit PAS activer la 2FA."""
        self.client.get(self.url)

        response = self.client.post(self.url, {"token": "000000"})
        # Redirige vers la page de setup avec un message d'erreur.
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_already_enabled_redirects_to_profile(self):
        """Si la 2FA est déjà active, la vue setup doit rediriger vers la page de profil."""
        self.user.two_factor_secret = pyotp.random_base32()
        self.user.two_factor_enabled = True
        self.user.save()

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:profile"))


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorVerifyTests(TestCase):
    """
    Tests pour la vue de vérification 2FA post-login (verify_2fa) et le middleware.

    Vérifie que le middleware bloque les vues protégées, qu'un code valide
    marque la session comme vérifiée, que les codes invalides incrémentent
    le compteur de tentatives, et que dépasser MAX_VERIFY_ATTEMPTS
    déconnecte l'utilisateur.
    """

    def setUp(self):
        """Crée un utilisateur avec 2FA déjà activée et stocke le secret pour la génération TOTP."""
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
        """Sans vérification 2FA, l'accès au tableau de bord doit rediriger vers verify_2fa."""
        self.client.force_login(self.user)
        response = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("verify", response.url)

    def test_post_valid_token_marks_session_verified(self):
        """Un code TOTP valide doit positionner le drapeau 2fa_verified dans la session."""
        self.client.force_login(self.user)
        valid_token = pyotp.TOTP(self.secret).now()

        response = self.client.post(self.url, {"token": valid_token})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_post_invalid_token_increments_attempts(self):
        """Un code TOTP invalide doit incrémenter le compteur de tentatives et retourner HTTP 400."""
        self.client.force_login(self.user)

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session.get(ATTEMPTS_SESSION_KEY), 1)
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))

    def test_too_many_failed_attempts_logs_user_out(self):
        """
        Après MAX_VERIFY_ATTEMPTS échecs, l'utilisateur doit être déconnecté
        et redirigé vers la page de connexion.
        """
        self.client.force_login(self.user)
        # Pré-amorce la session avec le nombre maximal d'échecs antérieurs.
        session = self.client.session
        session[ATTEMPTS_SESSION_KEY] = MAX_VERIFY_ATTEMPTS
        session.save()

        response = self.client.post(self.url, {"token": "000000"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("accounts:login"))
        # Confirme que l'utilisateur est bien déconnecté en testant une page protégée.
        response2 = self.client.get(reverse("dashboard:index"))
        self.assertEqual(response2.status_code, 302)
        self.assertIn("login", response2.url)


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorDisableTests(TestCase):
    """
    Tests pour la vue de désactivation 2FA (disable_2fa).

    Vérifie que la soumission du bon mot de passe désactive la 2FA et qu'un
    mauvais mot de passe est rejeté sans altérer l'état de la 2FA.
    """

    def setUp(self):
        """
        Crée un utilisateur avec 2FA activée, le connecte, et marque la session
        comme déjà 2FA-vérifiée pour que le middleware ne bloque pas le test.
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
        # Contourne le middleware 2FA en marquant la session comme déjà vérifiée.
        session = self.client.session
        session[VERIFIED_SESSION_KEY] = True
        session.save()
        self.url = reverse("accounts:disable_2fa")

    def test_disable_with_correct_password(self):
        """La soumission du bon mot de passe doit désactiver la 2FA et effacer le secret."""
        response = self.client.post(self.url, {"password": self.password})
        self.assertEqual(response.status_code, 302)

        self.user.refresh_from_db()
        self.assertFalse(self.user.two_factor_enabled)
        self.assertEqual(self.user.two_factor_secret, "")

    def test_disable_with_wrong_password_fails(self):
        """Un mot de passe incorrect doit être rejeté et la 2FA doit rester activée."""
        response = self.client.post(self.url, {"password": "WrongPass!"})
        self.assertEqual(response.status_code, 400)

        self.user.refresh_from_db()
        self.assertTrue(self.user.two_factor_enabled)
        self.assertNotEqual(self.user.two_factor_secret, "")


@override_settings(SECURE_SSL_REDIRECT=False)
class TwoFactorLoginFlowTests(TestCase):
    """
    Tests d'intégration pour le flux de connexion complet quand la 2FA est activée.

    Vérifie qu'après une vérification d'identifiants réussie, l'utilisateur
    est redirigé vers la page de vérification 2FA plutôt que directement
    vers le tableau de bord, et que la session n'est pas prématurément
    marquée comme vérifiée.
    """

    def test_login_with_2fa_redirects_to_verify(self):
        """
        Après une connexion réussie, un utilisateur avec 2FA activée doit être
        redirigé vers verify_2fa — PAS vers le tableau de bord — et la session
        ne doit PAS être marquée comme vérifiée tant que le code TOTP n'est
        pas soumis.
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
        # La session ne doit PAS être marquée comme 2FA-vérifiée avant la soumission du code.
        self.assertFalse(self.client.session.get(VERIFIED_SESSION_KEY))
