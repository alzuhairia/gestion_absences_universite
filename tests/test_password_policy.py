"""
Tests — politique de mots de passe et flux de réinitialisation.

Vérifie :
  - Le rejet des mots de passe faibles par les formulaires admin/étudiant.
  - Le verrou empêchant la création d'un second administrateur via la page de setup initial.
  - La politique de reset par un admin (force ``must_change_password``).
  - L'usage unique du jeton de réinitialisation et le rejet des utilisateurs désactivés.
"""
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.dashboard.forms_admin import UserForm
from apps.enrollments.forms import StudentCreationForm


class PasswordPolicyFormTests(TestCase):
    """Tests de validation des mots de passe sur les formulaires de création utilisateur."""

    def test_user_form_rejects_weak_password(self):
        """``UserForm`` doit refuser un mot de passe trop faible (sans majuscule/chiffre/symbole)."""
        form = UserForm(
            data={
                "nom": "Weak",
                "prenom": "User",
                "email": "weak-user@example.com",
                "role": User.Role.ETUDIANT,
                "actif": True,
                "password": "weakpass",
                "password_confirm": "weakpass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_user_form_accepts_strong_password(self):
        """``UserForm`` accepte un mot de passe conforme et active ``must_change_password``."""
        form = UserForm(
            data={
                "nom": "Strong",
                "prenom": "User",
                "email": "strong-user@example.com",
                "role": User.Role.ETUDIANT,
                "actif": True,
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)
        user = form.save()
        self.assertTrue(user.check_password("StrongPass123!"))
        self.assertTrue(user.must_change_password)

    def test_student_creation_form_rejects_weak_password(self):
        """``StudentCreationForm`` refuse un mot de passe ne respectant pas la politique."""
        form = StudentCreationForm(
            data={
                "nom": "Student",
                "prenom": "Weak",
                "email": "student-weak@example.com",
                "niveau": 1,
                "password": "weakpass",
                "password_confirm": "weakpass",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)

    def test_student_creation_form_accepts_strong_password(self):
        """``StudentCreationForm`` valide un mot de passe respectant la politique de force."""
        form = StudentCreationForm(
            data={
                "nom": "Student",
                "prenom": "Strong",
                "email": "student-strong@example.com",
                "niveau": 1,
                "password": "StrongPass123!",
                "password_confirm": "StrongPass123!",
            }
        )

        self.assertTrue(form.is_valid(), msg=form.errors)


@override_settings(SECURE_SSL_REDIRECT=False)
class InitialSetupTests(TestCase):
    """Tests for the one-time initial admin setup page."""

    def test_initial_setup_prevents_double_admin(self):
        """
        If an admin is created between loading the form (GET) and submitting
        it (POST), the select_for_update guard must reject the second creation.
        """
        # No admin exists yet — GET succeeds
        url = reverse("setup")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        # Meanwhile, another admin is created (simulates concurrent request)
        User.objects.create_superuser(
            email="first-admin@example.com",
            nom="First",
            prenom="Admin",
            password="StrongPass123!",
        )
        self.assertEqual(
            User.objects.filter(role=User.Role.ADMIN).count(), 1
        )

        # POST arrives — must be rejected (404) since an admin now exists
        response = self.client.post(url, {
            "prenom": "Second",
            "nom": "Admin",
            "email": "second-admin@example.com",
            "password": "StrongPass456!",
            "password_confirm": "StrongPass456!",
        })
        self.assertEqual(response.status_code, 404)

        # Only the first admin should exist
        self.assertEqual(
            User.objects.filter(role=User.Role.ADMIN).count(), 1
        )
        self.assertFalse(
            User.objects.filter(email="second-admin@example.com").exists()
        )

    def test_initial_setup_returns_404_when_admin_exists(self):
        """Both GET and POST return 404 if an admin already exists."""
        User.objects.create_superuser(
            email="existing-admin@example.com",
            nom="Existing",
            prenom="Admin",
            password="StrongPass123!",
        )
        url = reverse("setup")

        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(url, {}).status_code, 404)


class AdminPasswordResetPolicyTests(TestCase):
    """Tests du flux ``admin_user_reset_password`` (politique imposée par l'admin)."""

    def setUp(self):
        """Crée un admin et une cible étudiante, puis authentifie l'admin."""
        self.admin = User.objects.create_user(
            email="admin-password@example.com",
            nom="Admin",
            prenom="Password",
            password="AdminPass123!",
            role=User.Role.ADMIN,
        )
        self.target = User.objects.create_user(
            email="target-password@example.com",
            nom="Target",
            prenom="Password",
            password="InitialPass123!",
            role=User.Role.ETUDIANT,
            must_change_password=False,
        )
        self.client.force_login(self.admin)
        self.url = reverse(
            "dashboard:admin_user_reset_password", args=[self.target.id_utilisateur]
        )

    def test_admin_reset_rejects_weak_password(self):
        """Un mot de passe faible saisi par l'admin est refusé et l'ancien hash reste actif."""
        response = self.client.post(self.url, {"new_password": "weakpass"}, secure=True)

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("InitialPass123!"))
        self.assertFalse(self.target.must_change_password)

    def test_admin_reset_accepts_strong_password(self):
        """Un mot de passe conforme remplace l'ancien et force le changement au prochain login."""
        response = self.client.post(
            self.url, {"new_password": "StrongPass123!"}, secure=True
        )

        self.assertEqual(response.status_code, 302)
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("StrongPass123!"))
        self.assertTrue(self.target.must_change_password)


class PasswordResetTokenTests(TestCase):
    """Verify password reset token one-time use and inactive-user guard."""

    def setUp(self):
        """Crée un utilisateur étudiant cible pour générer puis valider un jeton de reset."""
        self.user = User.objects.create_user(
            email="reset@example.com",
            nom="Reset",
            prenom="User",
            password="OldPass123!",
            role=User.Role.ETUDIANT,
        )

    def _get_reset_url(self):
        """Generate a valid password-reset URL for self.user."""
        from django.contrib.auth.tokens import default_token_generator
        from django.utils.encoding import force_bytes
        from django.utils.http import urlsafe_base64_encode

        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        token = default_token_generator.make_token(self.user)
        return reverse(
            "accounts:password_reset_confirm",
            kwargs={"uidb64": uid, "token": token},
        )

    def test_password_reset_token_cannot_be_reused(self):
        """After a successful reset, the same token must be invalid."""
        url = self._get_reset_url()
        # First visit sets the token in the session and redirects
        resp1 = self.client.get(url, secure=True, follow=True)
        self.assertEqual(resp1.status_code, 200)
        self.assertTrue(resp1.context.get("validlink", False))

        # Submit the new password
        post_url = resp1.request["PATH_INFO"]
        resp2 = self.client.post(
            post_url,
            {"new_password1": "NewStrong123!", "new_password2": "NewStrong123!"},
            secure=True,
        )
        self.assertEqual(resp2.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewStrong123!"))

        # Re-using the original token must fail
        resp3 = self.client.get(url, secure=True, follow=True)
        self.assertFalse(resp3.context.get("validlink", True))

    def test_inactive_user_cannot_reset_password(self):
        """A deactivated user with a valid token must be blocked."""
        url = self._get_reset_url()
        # Deactivate after token generation
        self.user.actif = False
        self.user.save(update_fields=["actif"])

        resp = self.client.get(url, secure=True, follow=True)
        self.assertFalse(resp.context.get("validlink", True))
